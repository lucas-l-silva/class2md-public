import fcntl
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from core.config import get_settings


class TransicaoInvalida(Exception):
    pass


class RunnerJaEmExecucao(Exception):
    pass


TRANSICOES: dict[str, set[str]] = {
    "na_fila": {"rodando"},
    "rodando": {"concluido", "aguardando_humano", "falhou", "parcial"},
    "concluido": {"na_fila", "promovido"},
    "aguardando_humano": {"na_fila"},
    "falhou": {"na_fila"},
    # parou de propósito antes da nota (o usuário pediu só algumas etapas); retoma da fila
    "parcial": {"na_fila"},
    "promovido": set(),
}

_DDL = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, tipo TEXT NOT NULL, disciplina TEXT, data TEXT,
  status TEXT NOT NULL, input_hash TEXT, custo_usd REAL DEFAULT 0,
  criado_em TEXT, atualizado_em TEXT, erro TEXT);
CREATE TABLE IF NOT EXISTS passos(
  job_id TEXT, nome TEXT, status TEXT, tentativas INT DEFAULT 0,
  modelo TEXT, tokens_in INT, tokens_out INT, custo_usd REAL,
  input_hash TEXT, output_ref TEXT, iniciado_em TEXT, fim_em TEXT,
  PRIMARY KEY(job_id, nome));
CREATE TABLE IF NOT EXISTS aprovacoes(
  id TEXT PRIMARY KEY, job_id TEXT, acao TEXT, payload_ref TEXT,
  status TEXT DEFAULT 'pendente', decidido_em TEXT);
CREATE TABLE IF NOT EXISTS arquivos(
  sha256 TEXT PRIMARY KEY, nome_final TEXT, disciplina TEXT, tirada_em TEXT,
  job_id TEXT, ingerido_em TEXT);
CREATE TABLE IF NOT EXISTS avaliacoes(
  job_id TEXT PRIMARY KEY, nota_qualidade INT NOT NULL, avaliado_em TEXT);
CREATE TABLE IF NOT EXISTS pdfs(
  sha256 TEXT PRIMARY KEY, caminho TEXT NOT NULL, nome_arquivo TEXT,
  disciplina TEXT, tipo TEXT, modo TEXT, paginas INT, chars_total INT,
  data_aula TEXT, tem_texto_nativo INT, indexado_em TEXT, registrado_em TEXT);
CREATE TABLE IF NOT EXISTS compromissos(
  id TEXT PRIMARY KEY, chave TEXT NOT NULL UNIQUE, disciplina TEXT NOT NULL,
  tipo TEXT NOT NULL, titulo TEXT NOT NULL, data TEXT, hora TEXT, recorrencia TEXT,
  status TEXT NOT NULL, origem_job TEXT, origem_trecho TEXT, confianca REAL,
  criado_em TEXT, atualizado_em TEXT, campos_editados TEXT);
CREATE INDEX IF NOT EXISTS idx_compromissos_disciplina_data
  ON compromissos(disciplina, data);
-- Livro-caixa append-only. `passos` guarda o ESTADO do passo (upsert por job+nome), e
-- por isso não serve para somar dinheiro: reprocessar um job sobrescreveria o custo da
-- tentativa anterior, que foi gasta de verdade. Aqui nada é sobrescrito.
CREATE TABLE IF NOT EXISTS custos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, passo TEXT, modelo TEXT,
  tokens_in INT, tokens_out INT, custo_usd REAL NOT NULL, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_custos_em ON custos(em);
-- Um material PERTENCE a uma aula (pdfs.numero_aula), mas pode ser CITADO em outra: o
-- professor retoma a questão 6 da lista da aula 1 quando chega na intercalação, na aula
-- 2. São relações diferentes — sobrescrever `numero_aula` para registrar a citação faria
-- o material sumir da aula de origem. Aqui a citação é uma linha à parte.
CREATE TABLE IF NOT EXISTS referencias(
  id INTEGER PRIMARY KEY AUTOINCREMENT, sha256 TEXT NOT NULL, disciplina TEXT NOT NULL,
  numero_aula INTEGER NOT NULL, detalhe TEXT, origem TEXT, criado_em TEXT,
  UNIQUE(sha256, numero_aula, detalhe));
CREATE INDEX IF NOT EXISTS idx_referencias_aula ON referencias(disciplina, numero_aula);
-- Histórico de cada compromisso, append-only. `compromissos.status` guarda o estado
-- ATUAL e nada mais: quem confirmou uma prova em agosto e a concluiu em setembro não
-- consegue reconstruir isso de uma coluna que só tem o último valor. Aqui nada é
-- sobrescrito, então "quando eu confirmei isso?" tem resposta.
CREATE TABLE IF NOT EXISTS eventos_compromisso(
  id INTEGER PRIMARY KEY AUTOINCREMENT, compromisso_id TEXT NOT NULL,
  acao TEXT NOT NULL, de TEXT, para TEXT, origem TEXT NOT NULL, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_eventos_compromisso
  ON eventos_compromisso(compromisso_id, em);
-- Ocultar é arrumação de tela, não julgamento: o evento continua valendo e continua
-- exportando para o .ics. `descartado` é que significa "a proposta estava errada".
-- A `data` guarda QUAL ocorrência sumiu — é o que permite esconder uma sexta de
-- monitoria (feriado, semana de prova) sem derrubar as outras onze. NULL esconde o
-- compromisso inteiro, que é o caso de quem não tem data.
CREATE TABLE IF NOT EXISTS ocultacoes(
  compromisso_id TEXT NOT NULL, data TEXT, origem TEXT, criado_em TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ocultacoes_unica
  ON ocultacoes(compromisso_id, IFNULL(data, ''));
CREATE TABLE IF NOT EXISTS comentarios(
  id INTEGER PRIMARY KEY AUTOINCREMENT, compromisso_id TEXT NOT NULL,
  texto TEXT NOT NULL, origem TEXT, criado_em TEXT);
CREATE INDEX IF NOT EXISTS idx_comentarios_compromisso
  ON comentarios(compromisso_id, criado_em);
"""

# colunas adicionadas depois da criação inicial das tabelas; ALTER TABLE não tem
# "IF NOT EXISTS" no SQLite, então tentamos e ignoramos "coluna já existe".
_MIGRACOES_ARQUIVOS = (
    "disciplina TEXT",
    "tirada_em TEXT",
    "origem TEXT",
    # pasta | exif | escrita | escrita_reconciliada — de onde veio a data da aula
    "data_fonte TEXT",
)
_MIGRACOES_JOBS = (
    "data TEXT",
    "aviso_reprocessamento TEXT",
    "forcar_reprocessamento TEXT",
    "numero_aula INTEGER",
    # etapas pedidas e concluídas, separadas por vírgula; vazio quando rodou tudo
    "etapas_feitas TEXT",
)
_MIGRACOES_COMPROMISSOS = ("campos_editados TEXT",)
_MIGRACOES_PDFS = (
    "vigencia TEXT",
    "numero_aula INTEGER",
    "titulo_material TEXT",
    "autor TEXT",
    "vinculo_fonte TEXT",
    "origem_url TEXT",
    "ocr_em TEXT",
)


def conectar() -> sqlite3.Connection:
    caminho = get_settings().agent_data_dir / "estado.db"
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)

    for tabela, colunas in (
        ("arquivos", _MIGRACOES_ARQUIVOS),
        ("jobs", _MIGRACOES_JOBS),
        ("pdfs", _MIGRACOES_PDFS),
        ("compromissos", _MIGRACOES_COMPROMISSOS),
    ):
        for coluna in colunas:
            try:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna}")
            except sqlite3.OperationalError as erro:
                if "duplicate column" not in str(erro):
                    raise

    _semear_custos_de_passos(conn)
    _semear_log_de_compromissos(conn)
    conn.commit()
    return conn


def criar_job(
    tipo: str,
    disciplina: str | None = None,
    data: str | None = None,
    input_hash: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    agora = datetime.now(UTC).isoformat()
    conn = conectar()
    conn.execute(
        "INSERT INTO jobs(id, tipo, disciplina, data, status, input_hash, criado_em, atualizado_em) "
        "VALUES (?, ?, ?, ?, 'na_fila', ?, ?, ?)",
        (job_id, tipo, disciplina, data, input_hash, agora, agora),
    )
    conn.commit()
    return job_id


def transicionar(job_id: str, novo_status: str) -> None:
    conn = conectar()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"job não encontrado: {job_id}")

    atual = row["status"]
    if novo_status not in TRANSICOES.get(atual, set()):
        raise TransicaoInvalida(f"{atual} -> {novo_status} não é permitido")

    conn.execute(
        "UPDATE jobs SET status=?, atualizado_em=? WHERE id=?",
        (novo_status, datetime.now(UTC).isoformat(), job_id),
    )
    conn.commit()


def enfileirar(job_id: str) -> None:
    conn = conectar()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"job não encontrado: {job_id}")
    if row["status"] == "na_fila":
        return  # idempotente
    transicionar(job_id, "na_fila")


def proximo_da_fila(
    somente_job: str | None = None, ignorar: frozenset[str] = frozenset()
) -> sqlite3.Row | None:
    """Próximo job na fila. `somente_job` restringe a um job; `ignorar` pula ids que o
    chamador decidiu não rodar nesta execução."""
    conn = conectar()
    consulta = "SELECT * FROM jobs WHERE status='na_fila'"
    parametros: list[str] = []
    if somente_job is not None:
        consulta += " AND id=?"
        parametros.append(somente_job)
    if ignorar:
        consulta += f" AND id NOT IN ({','.join('?' * len(ignorar))})"
        parametros.extend(sorted(ignorar))
    consulta += " ORDER BY criado_em LIMIT 1"
    return conn.execute(consulta, parametros).fetchone()


def registrar_etapas_feitas(job_id: str, etapas: list[str] | None) -> None:
    conn = conectar()
    conn.execute(
        "UPDATE jobs SET etapas_feitas=? WHERE id=?",
        (",".join(etapas) if etapas else None, job_id),
    )
    conn.commit()


def listar_jobs(status: str | None = None, limite: int = 10) -> list[sqlite3.Row]:
    conn = conectar()
    if status is not None:
        return conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY atualizado_em DESC LIMIT ?",
            (status, limite),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM jobs ORDER BY atualizado_em DESC LIMIT ?", (limite,)
    ).fetchall()


def registrar_passo(
    job_id: str,
    nome: str,
    status: str,
    tentativas: int = 0,
    modelo: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    custo_usd: float | None = None,
    input_hash: str | None = None,
    output_ref: str | None = None,
) -> None:
    agora = datetime.now(UTC).isoformat()
    conn = conectar()
    conn.execute(
        """
        INSERT INTO passos(
            job_id, nome, status, tentativas, modelo, tokens_in, tokens_out,
            custo_usd, input_hash, output_ref, iniciado_em, fim_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, nome) DO UPDATE SET
            status=excluded.status, tentativas=excluded.tentativas, modelo=excluded.modelo,
            tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out,
            custo_usd=excluded.custo_usd, input_hash=excluded.input_hash,
            output_ref=excluded.output_ref, fim_em=excluded.fim_em
        """,
        (
            job_id,
            nome,
            status,
            tentativas,
            modelo,
            tokens_in,
            tokens_out,
            custo_usd,
            input_hash,
            output_ref,
            agora,
            agora,
        ),
    )
    conn.commit()


def registrar_custo_lancamento(
    job_id: str,
    passo: str,
    modelo: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    custo_usd: float,
) -> None:
    """Lança uma chamada de modelo no livro-caixa. Nunca sobrescreve nada."""
    conn = conectar()
    conn.execute(
        "INSERT INTO custos(job_id, passo, modelo, tokens_in, tokens_out, custo_usd, em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            job_id,
            passo,
            modelo,
            tokens_in,
            tokens_out,
            custo_usd,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


#: bump quando uma migração de dados (não de schema) precisar rodar uma única vez
#: cada migração de DADOS tem o próprio número. Um contador único não serve: bumpar o
#: valor faria toda migração anterior rodar de novo, e a de `custos` lançaria o dinheiro
#: em dobro. `user_version` guarda a MAIOR já aplicada.
MIGRACAO_CUSTOS = 1
MIGRACAO_LOG_COMPROMISSOS = 2
VERSAO_ESQUEMA = MIGRACAO_LOG_COMPROMISSOS


def _semear_custos_de_passos(conn: sqlite3.Connection) -> None:
    """Backfill único: bancos criados antes do livro-caixa têm o histórico em `passos`.

    Guardado por `PRAGMA user_version`, não por "a tabela está vazia": esse teste
    voltaria a ser verdadeiro entre o primeiro lançamento e o próximo `conectar()`,
    e o backfill duplicaria o custo recém-lançado.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= MIGRACAO_CUSTOS:
        return
    conn.execute(
        "INSERT INTO custos(job_id, passo, modelo, tokens_in, tokens_out, custo_usd, em) "
        "SELECT job_id, nome, modelo, tokens_in, tokens_out, custo_usd, fim_em FROM passos "
        "WHERE custo_usd IS NOT NULL AND custo_usd > 0 AND fim_em IS NOT NULL"
    )
    conn.execute(f"PRAGMA user_version = {MIGRACAO_CUSTOS}")
    conn.commit()


def _semear_log_de_compromissos(conn: sqlite3.Connection) -> None:
    """Backfill único do histórico que nunca foi observado.

    Antes desta tabela, um compromisso só guardava `criado_em`, `atualizado_em` e o
    status atual. Dá para inferir "foi criado" e "chegou ao status X", e nada além disso
    — quantas vezes mudou de ideia no meio, ninguém sabe. Por isso a origem é
    `reconstruido`: quem ler o log precisa distinguir o que foi visto acontecer do que
    foi deduzido depois.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= MIGRACAO_LOG_COMPROMISSOS:
        return
    conn.execute(
        "INSERT INTO eventos_compromisso(compromisso_id, acao, de, para, origem, em) "
        "SELECT id, 'criado', NULL, 'proposto', 'reconstruido', criado_em "
        "FROM compromissos WHERE criado_em IS NOT NULL"
    )
    # só registra a transição para quem já saiu de 'proposto'
    conn.execute(
        "INSERT INTO eventos_compromisso(compromisso_id, acao, de, para, origem, em) "
        "SELECT id, status, 'proposto', status, 'reconstruido', atualizado_em "
        "FROM compromissos WHERE status != 'proposto' AND atualizado_em IS NOT NULL"
    )
    conn.execute(f"PRAGMA user_version = {MIGRACAO_LOG_COMPROMISSOS}")
    conn.commit()


def custo_do_mes(ano: int | None = None, mes: int | None = None) -> float:
    agora = datetime.now(UTC)
    ano = ano or agora.year
    mes = mes or agora.month
    prefixo = f"{ano:04d}-{mes:02d}"

    conn = conectar()
    row = conn.execute(
        "SELECT COALESCE(SUM(custo_usd), 0) AS total FROM custos WHERE substr(em, 1, 7) = ?",
        (prefixo,),
    ).fetchone()
    return row["total"]


def ja_ingerido(sha256: str) -> bool:
    conn = conectar()
    row = conn.execute("SELECT 1 FROM arquivos WHERE sha256=?", (sha256,)).fetchone()
    return row is not None


def arquivo_por_sha(sha256: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute("SELECT * FROM arquivos WHERE sha256=?", (sha256,)).fetchone()


def registrar_arquivo(
    sha256: str,
    nome_final: str,
    disciplina: str | None = None,
    tirada_em: str | None = None,
    job_id: str | None = None,
    origem: str = "aula",
    data_fonte: str | None = None,
) -> None:
    conn = conectar()
    conn.execute(
        "INSERT INTO arquivos(sha256, nome_final, disciplina, tirada_em, job_id, origem, "
        "ingerido_em, data_fonte) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sha256,
            nome_final,
            disciplina,
            tirada_em,
            job_id,
            origem,
            datetime.now(UTC).isoformat(),
            data_fonte,
        ),
    )
    conn.commit()


def fotos_pendentes(origem: str = "aula") -> list[sqlite3.Row]:
    """Fotos ainda sem job. Filtra por origem: foto de monitoria não vira nota de aula."""
    conn = conectar()
    return conn.execute(
        "SELECT * FROM arquivos WHERE job_id IS NULL AND COALESCE(origem, 'aula') = ?",
        (origem,),
    ).fetchall()


def fotos_do_job(job_id: str) -> list[sqlite3.Row]:
    conn = conectar()
    return conn.execute("SELECT * FROM arquivos WHERE job_id=?", (job_id,)).fetchall()


def job_por_input_hash(input_hash: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute("SELECT * FROM jobs WHERE input_hash=?", (input_hash,)).fetchone()


def job_por_data_disciplina(tipo: str, data: str, disciplina: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute(
        "SELECT * FROM jobs WHERE tipo=? AND data=? AND disciplina=?",
        (tipo, data, disciplina),
    ).fetchone()


def job_por_id(job_id: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def job_por_prefixo_id(prefixo: str) -> sqlite3.Row | None:
    exato = job_por_id(prefixo)
    if exato is not None:
        return exato
    conn = conectar()
    candidatos = conn.execute("SELECT * FROM jobs WHERE id LIKE ?", (f"{prefixo}%",)).fetchall()
    return candidatos[0] if len(candidatos) == 1 else None


def registrar_numero_aula(job_id: str, numero_aula: int | None) -> None:
    """Liga o job à aula do programa. É por aqui que material e nota se encontram."""
    conn = conectar()
    conn.execute(
        "UPDATE jobs SET numero_aula=?, atualizado_em=? WHERE id=?",
        (numero_aula, datetime.now(UTC).isoformat(), job_id),
    )
    conn.commit()


def registrar_aviso_job(job_id: str, aviso: str | None) -> None:
    conn = conectar()
    conn.execute("UPDATE jobs SET aviso_reprocessamento=? WHERE id=?", (aviso, job_id))
    conn.commit()


def marcar_reprocessamento(job_id: str, passo: str | None = None) -> None:
    # "*" força todos os passos; um nome (== Agente.nome) restringe a invalidação a ele.
    conn = conectar()
    conn.execute("UPDATE jobs SET forcar_reprocessamento=? WHERE id=?", (passo or "*", job_id))
    conn.commit()


def limpar_reprocessamento(job_id: str) -> None:
    conn = conectar()
    conn.execute("UPDATE jobs SET forcar_reprocessamento=NULL WHERE id=?", (job_id,))
    conn.commit()


def marcar_promovido(job_id: str, nota_qualidade: int) -> None:
    # transicionar já valida existência do job e a transição concluido->promovido; feita
    # antes do INSERT pra não gravar avaliação de um job que nunca chegou a concluido.
    transicionar(job_id, "promovido")
    conn = conectar()
    conn.execute(
        "INSERT INTO avaliacoes(job_id, nota_qualidade, avaliado_em) VALUES (?, ?, ?)",
        (job_id, nota_qualidade, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def vincular_arquivo_a_job(sha256: str, job_id: str) -> None:
    conn = conectar()
    conn.execute("UPDATE arquivos SET job_id=? WHERE sha256=?", (job_id, sha256))
    conn.commit()


def registrar_pdf_estado(
    sha256: str,
    caminho: str,
    nome_arquivo: str,
    disciplina: str | None,
    tipo: str,
    modo: str,
    paginas: int,
    chars_total: int,
    tem_texto_nativo: bool,
    data_aula: str | None = None,
    vigencia: str = "atual",
    numero_aula: int | None = None,
    titulo_material: str | None = None,
    autor: str | None = None,
    vinculo_fonte: str | None = None,
    origem_url: str | None = None,
) -> None:
    conn = conectar()
    conn.execute(
        """
        INSERT INTO pdfs(
            sha256, caminho, nome_arquivo, disciplina, tipo, modo, paginas,
            chars_total, data_aula, tem_texto_nativo, vigencia, numero_aula,
            titulo_material, autor, vinculo_fonte, origem_url, registrado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sha256) DO UPDATE SET
            caminho=excluded.caminho, nome_arquivo=excluded.nome_arquivo,
            disciplina=excluded.disciplina, tipo=excluded.tipo, modo=excluded.modo,
            paginas=excluded.paginas, chars_total=excluded.chars_total,
            data_aula=excluded.data_aula, tem_texto_nativo=excluded.tem_texto_nativo,
            vigencia=excluded.vigencia, titulo_material=excluded.titulo_material,
            -- vínculo e autoria só avançam: uma revarredura sem essa informação não
            -- pode apagar o que você (ou o coletor) já resolveu.
            numero_aula=COALESCE(excluded.numero_aula, pdfs.numero_aula),
            autor=COALESCE(excluded.autor, pdfs.autor),
            vinculo_fonte=COALESCE(excluded.vinculo_fonte, pdfs.vinculo_fonte),
            origem_url=COALESCE(excluded.origem_url, pdfs.origem_url)
        """,
        (
            sha256,
            caminho,
            nome_arquivo,
            disciplina,
            tipo,
            modo,
            paginas,
            chars_total,
            data_aula,
            int(tem_texto_nativo),
            vigencia,
            numero_aula,
            titulo_material,
            autor,
            vinculo_fonte,
            origem_url,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def marcar_pdf_ocr(sha256: str) -> None:
    """Registra que o texto deste PDF foi recuperado por visão, não lido nativamente."""
    conn = conectar()
    conn.execute(
        "UPDATE pdfs SET ocr_em=? WHERE sha256=?",
        (datetime.now(UTC).isoformat(), sha256),
    )
    conn.commit()


def atualizar_caminho_pdf(sha256: str, caminho: str, nome_arquivo: str) -> None:
    """Conserta o caminho de um PDF que mudou de lugar ou de nome.

    O registro é chaveado por hash do conteúdo, então mover/renomear o arquivo não
    cria linha nova — mas deixaria a linha antiga apontando para um caminho morto.
    """
    conn = conectar()
    conn.execute(
        "UPDATE pdfs SET caminho=?, nome_arquivo=? WHERE sha256=?",
        (caminho, nome_arquivo, sha256),
    )
    conn.commit()


def vincular_pdf_a_aula(
    sha256: str, numero_aula: int | None, vinculo_fonte: str | None = None
) -> None:
    conn = conectar()
    conn.execute(
        "UPDATE pdfs SET numero_aula=?, vinculo_fonte=? WHERE sha256=?",
        (numero_aula, vinculo_fonte, sha256),
    )
    conn.commit()


def registrar_referencia(
    sha256: str,
    disciplina: str,
    numero_aula: int,
    detalhe: str | None = None,
    origem: str = "manual",
) -> None:
    """Registra que este material foi **citado** na aula N, sem mudar a aula dele."""
    conn = conectar()
    conn.execute(
        "INSERT OR IGNORE INTO referencias"
        "(sha256, disciplina, numero_aula, detalhe, origem, criado_em)"
        " VALUES (?,?,?,?,?,?)",
        (
            sha256,
            disciplina,
            numero_aula,
            detalhe,
            origem,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def referencias_da_aula(disciplina: str, numero_aula: int) -> list[sqlite3.Row]:
    conn = conectar()
    return conn.execute(
        "SELECT r.*, p.nome_arquivo, p.caminho, p.tipo FROM referencias r"
        " JOIN pdfs p ON p.sha256 = r.sha256"
        " WHERE r.disciplina=? AND r.numero_aula=? ORDER BY p.nome_arquivo",
        (disciplina, numero_aula),
    ).fetchall()


def pdfs_por_numero_aula(
    disciplina: str, numero_aula: int, vigencia: str | None = None
) -> list[sqlite3.Row]:
    conn = conectar()
    if vigencia is not None:
        return conn.execute(
            "SELECT * FROM pdfs WHERE disciplina=? AND numero_aula=? AND vigencia=? "
            "ORDER BY nome_arquivo",
            (disciplina, numero_aula, vigencia),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM pdfs WHERE disciplina=? AND numero_aula=? ORDER BY nome_arquivo",
        (disciplina, numero_aula),
    ).fetchall()


def pdfs_sem_vinculo(disciplina: str | None = None) -> list[sqlite3.Row]:
    conn = conectar()
    if disciplina is not None:
        return conn.execute(
            "SELECT * FROM pdfs WHERE numero_aula IS NULL AND disciplina=? ORDER BY nome_arquivo",
            (disciplina,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM pdfs WHERE numero_aula IS NULL ORDER BY disciplina, nome_arquivo"
    ).fetchall()


def pdf_por_sha(sha256: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute("SELECT * FROM pdfs WHERE sha256=?", (sha256,)).fetchone()


def pdfs_por_disciplina(disciplina: str, tipo: str | None = None) -> list[sqlite3.Row]:
    conn = conectar()
    if tipo is not None:
        return conn.execute(
            "SELECT * FROM pdfs WHERE disciplina=? AND tipo=? ORDER BY nome_arquivo",
            (disciplina, tipo),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM pdfs WHERE disciplina=? ORDER BY nome_arquivo", (disciplina,)
    ).fetchall()


def pdfs_por_tipo(tipo: str) -> list[sqlite3.Row]:
    conn = conectar()
    return conn.execute(
        "SELECT * FROM pdfs WHERE tipo=? ORDER BY disciplina, nome_arquivo", (tipo,)
    ).fetchall()


def pdfs_por_aula(disciplina: str, data: str) -> list[sqlite3.Row]:
    conn = conectar()
    return conn.execute(
        "SELECT * FROM pdfs WHERE disciplina=? AND data_aula=? ORDER BY nome_arquivo",
        (disciplina, data),
    ).fetchall()


def marcar_pdf_indexado(sha256: str) -> None:
    conn = conectar()
    conn.execute(
        "UPDATE pdfs SET indexado_em=? WHERE sha256=?",
        (datetime.now(UTC).isoformat(), sha256),
    )
    conn.commit()


@contextmanager
def lock_runner():
    caminho = get_settings().agent_data_dir / ".runner.lock"
    arquivo = open(caminho, "w")
    try:
        fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        arquivo.close()
        raise RunnerJaEmExecucao("já existe um runner em execução") from None

    try:
        yield
    finally:
        fcntl.flock(arquivo, fcntl.LOCK_UN)
        arquivo.close()


STATUS_COMPROMISSO = ("proposto", "confirmado", "descartado", "concluido")


def registrar_compromisso(
    chave: str,
    disciplina: str,
    tipo: str,
    titulo: str,
    data: str | None = None,
    hora: str | None = None,
    recorrencia: str | None = None,
    origem_job: str | None = None,
    origem_trecho: str | None = None,
    confianca: float | None = None,
) -> str:
    """Insere ou atualiza um compromisso proposto, identificado por `chave`.

    O status NÃO é tocado no conflito: uma reextração da mesma aula não pode
    "despromover" algo que o humano já confirmou nem ressuscitar o que ele descartou.

    Campo que você editou à mão também não é tocado. Sem isso, corrigir a data de uma
    prova e depois reprocessar a aula devolveria silenciosamente a data errada — e a
    correção some sem aviso, que é o pior jeito de perder trabalho.
    """
    conn = conectar()
    agora = datetime.now(UTC).isoformat()
    existente = conn.execute("SELECT * FROM compromissos WHERE chave=?", (chave,)).fetchone()
    if existente:
        protegidos = set(json.loads(existente["campos_editados"] or "[]"))
        atual = dict(existente)
        valores = {
            "titulo": titulo,
            "data": data,
            "hora": hora,
            "recorrencia": recorrencia,
        }
        for campo in protegidos & valores.keys():
            valores[campo] = atual[campo]

        conn.execute(
            """
            UPDATE compromissos SET titulo=?, data=?, hora=?, recorrencia=?,
                origem_job=COALESCE(?, origem_job), origem_trecho=COALESCE(?, origem_trecho),
                confianca=?, atualizado_em=?
            WHERE chave=?
            """,
            (
                valores["titulo"],
                valores["data"],
                valores["hora"],
                valores["recorrencia"],
                origem_job,
                origem_trecho,
                confianca,
                agora,
                chave,
            ),
        )
        conn.commit()
        return existente["id"]

    novo_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO compromissos(
            id, chave, disciplina, tipo, titulo, data, hora, recorrencia, status,
            origem_job, origem_trecho, confianca, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposto', ?, ?, ?, ?, ?)
        """,
        (
            novo_id,
            chave,
            disciplina,
            tipo,
            titulo,
            data,
            hora,
            recorrencia,
            origem_job,
            origem_trecho,
            confianca,
            agora,
            agora,
        ),
    )
    conn.commit()
    return novo_id


def listar_compromissos(
    disciplina: str | None = None, status: str | None = None
) -> list[sqlite3.Row]:
    conn = conectar()
    condicoes, parametros = [], []
    if disciplina is not None:
        condicoes.append("disciplina=?")
        parametros.append(disciplina)
    if status is not None:
        condicoes.append("status=?")
        parametros.append(status)
    onde = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    return conn.execute(
        f"SELECT * FROM compromissos {onde} ORDER BY COALESCE(data, '9999'), titulo",
        parametros,
    ).fetchall()


def compromisso_por_prefixo_id(prefixo: str) -> sqlite3.Row | None:
    conn = conectar()
    return conn.execute("SELECT * FROM compromissos WHERE id LIKE ? || '%'", (prefixo,)).fetchone()


def mudar_status_compromisso(id_compromisso: str, novo_status: str, origem: str = "cli") -> None:
    """Único caminho de mudança de status — por isso o log fica aqui dentro.

    Se o registro no log dependesse de quem chama lembrar de registrar, mais cedo ou mais
    tarde uma transição escaparia e o histórico passaria a mentir por omissão.
    """
    if novo_status not in STATUS_COMPROMISSO:
        raise ValueError(f"status inválido: {novo_status}")

    conn = conectar()
    atual = conn.execute("SELECT status FROM compromissos WHERE id=?", (id_compromisso,)).fetchone()
    if atual is None:
        raise ValueError(f"compromisso não encontrado: {id_compromisso}")
    if atual["status"] == novo_status:
        return  # nada mudou: não polui o log com uma linha sem transição

    agora = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE compromissos SET status=?, atualizado_em=? WHERE id=?",
        (novo_status, agora, id_compromisso),
    )
    conn.execute(
        "INSERT INTO eventos_compromisso(compromisso_id, acao, de, para, origem, em) "
        "VALUES (?,?,?,?,?,?)",
        (id_compromisso, novo_status, atual["status"], novo_status, origem, agora),
    )
    conn.commit()


CAMPOS_EDITAVEIS = ("titulo", "data", "hora", "recorrencia", "tipo", "disciplina")


def editar_compromisso(id_compromisso: str, origem: str = "cli", **campos) -> None:
    """Altera campos do compromisso e os marca como seus.

    Marcar é o que impede a próxima reextração de desfazer a edição — e cada mudança
    entra no log, para você poder responder "quem mudou essa data?".
    """
    invalidos = set(campos) - set(CAMPOS_EDITAVEIS)
    if invalidos:
        raise ValueError(f"campo não editável: {', '.join(sorted(invalidos))}")

    conn = conectar()
    atual = conn.execute("SELECT * FROM compromissos WHERE id=?", (id_compromisso,)).fetchone()
    if atual is None:
        raise ValueError(f"compromisso não encontrado: {id_compromisso}")

    mudancas = {c: v for c, v in campos.items() if v != atual[c]}
    if not mudancas:
        return

    agora = datetime.now(UTC).isoformat()
    editados = sorted(set(json.loads(atual["campos_editados"] or "[]")) | set(mudancas))
    atribuicoes = ", ".join(f"{c}=?" for c in mudancas)
    conn.execute(
        f"UPDATE compromissos SET {atribuicoes}, campos_editados=?, atualizado_em=? WHERE id=?",
        (*mudancas.values(), json.dumps(editados), agora, id_compromisso),
    )
    for campo, novo in mudancas.items():
        conn.execute(
            "INSERT INTO eventos_compromisso(compromisso_id, acao, de, para, origem, em) "
            "VALUES (?,?,?,?,?,?)",
            (id_compromisso, f"editou:{campo}", atual[campo], novo, origem, agora),
        )
    conn.commit()


def _registrar_no_log(
    conn: sqlite3.Connection,
    id_compromisso: str,
    acao: str,
    para: str | None,
    origem: str,
) -> None:
    conn.execute(
        "INSERT INTO eventos_compromisso(compromisso_id, acao, de, para, origem, em) "
        "VALUES (?,?,?,?,?,?)",
        (id_compromisso, acao, None, para, origem, datetime.now(UTC).isoformat()),
    )


def ocultar_compromisso(id_compromisso: str, data: str | None = None, origem: str = "cli") -> None:
    """Some da página; continua no `.ics`. `data=None` esconde o compromisso inteiro."""
    conn = conectar()
    conn.execute(
        "INSERT OR IGNORE INTO ocultacoes(compromisso_id, data, origem, criado_em) "
        "VALUES (?,?,?,?)",
        (id_compromisso, data, origem, datetime.now(UTC).isoformat()),
    )
    _registrar_no_log(conn, id_compromisso, "ocultou", data or "(tudo)", origem)
    conn.commit()


def reexibir_compromisso(id_compromisso: str, data: str | None = None, origem: str = "cli") -> None:
    """Sem `data`, devolve tudo do compromisso — inclusive as ocorrências escondidas
    uma a uma, que é o que se espera de "mostrar de novo"."""
    conn = conectar()
    if data is None:
        conn.execute("DELETE FROM ocultacoes WHERE compromisso_id=?", (id_compromisso,))
    else:
        conn.execute(
            "DELETE FROM ocultacoes WHERE compromisso_id=? AND data=?",
            (id_compromisso, data),
        )
    _registrar_no_log(conn, id_compromisso, "reexibiu", data or "(tudo)", origem)
    conn.commit()


def ocultacoes() -> dict[str, set[str | None]]:
    """{id_compromisso: {datas ocultas}}. `None` no conjunto = o compromisso todo."""
    conn = conectar()
    mapa: dict[str, set[str | None]] = {}
    for linha in conn.execute("SELECT compromisso_id, data FROM ocultacoes"):
        mapa.setdefault(linha["compromisso_id"], set()).add(linha["data"])
    return mapa


def comentar_compromisso(id_compromisso: str, texto: str, origem: str = "cli") -> None:
    """Acrescenta um comentário carimbado. Nada é sobrescrito — como o resto do histórico."""
    texto = texto.strip()
    if not texto:
        raise ValueError("comentário vazio")

    conn = conectar()
    agora = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO comentarios(compromisso_id, texto, origem, criado_em) VALUES (?,?,?,?)",
        (id_compromisso, texto, origem, agora),
    )
    _registrar_no_log(conn, id_compromisso, "comentou", texto[:60], origem)
    conn.commit()


def comentarios_de(id_compromisso: str) -> list[sqlite3.Row]:
    conn = conectar()
    return conn.execute(
        "SELECT * FROM comentarios WHERE compromisso_id=? ORDER BY criado_em",
        (id_compromisso,),
    ).fetchall()


def comentarios_por_compromisso() -> dict[str, list[sqlite3.Row]]:
    """Todos de uma vez — a página precisa dos comentários de todos os eventos."""
    conn = conectar()
    mapa: dict[str, list] = {}
    for linha in conn.execute("SELECT * FROM comentarios ORDER BY criado_em"):
        mapa.setdefault(linha["compromisso_id"], []).append(linha)
    return mapa


def historico_compromisso(id_compromisso: str | None = None, limite: int = 50) -> list[sqlite3.Row]:
    """Log de eventos, do mais recente para o mais antigo. Sem id, de todos."""
    conn = conectar()
    if id_compromisso is not None:
        return conn.execute(
            "SELECT e.*, c.titulo, c.disciplina FROM eventos_compromisso e"
            " LEFT JOIN compromissos c ON c.id = e.compromisso_id"
            " WHERE e.compromisso_id = ? ORDER BY e.em DESC, e.id DESC LIMIT ?",
            (id_compromisso, limite),
        ).fetchall()
    return conn.execute(
        "SELECT e.*, c.titulo, c.disciplina FROM eventos_compromisso e"
        " LEFT JOIN compromissos c ON c.id = e.compromisso_id"
        " ORDER BY e.em DESC, e.id DESC LIMIT ?",
        (limite,),
    ).fetchall()
