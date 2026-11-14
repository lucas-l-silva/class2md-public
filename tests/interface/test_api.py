import json

from apoio_interface import CHAVE_DE_TESTE, chamar, foto

from core import estado

ETAPAS_FOTO = {"leitura", "nota", "flashcards", "conceitos", "disciplina"}


def test_estado_sem_chave(app, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    r = chamar(app, "GET", "/api/estado")
    assert r.json()["chave_configurada"] is False
    r = chamar(
        app, "POST", "/api/processar", {"confirmado": True, "envio_id": "x", "etapas": ["leitura"]}
    )
    assert r.status == 400 and r.json()["erro"] == "sem_chave"
    assert chamar(app, "POST", "/api/estimativa", {}).status == 400


def test_estado_com_chave_traz_limites_e_nunca_a_chave(app):
    r = chamar(app, "GET", "/api/estado")
    d = r.json()
    assert d["chave_configurada"] is True
    assert d["limites"]["max_fotos_por_envio"] == 60
    assert d["recursos"] == {"duvidas": False, "economia": False, "pdf": False}
    assert CHAVE_DE_TESTE not in r.texto


def test_plano_de_foto_lista_cinco_etapas_com_dependencias(app):
    d = chamar(app, "GET", "/api/plano?material=foto_aula").json()
    assert {e["nome"] for e in d["etapas"]} == ETAPAS_FOTO
    por_nome = {e["nome"]: e for e in d["etapas"]}
    assert por_nome["flashcards"]["depende_de"] == ["nota"]


def test_plano_nao_marca_nada(app):
    texto = chamar(app, "GET", "/api/plano?material=foto_aula").texto
    assert "marcada" not in texto and "padrao" not in texto and "default" not in texto


def test_plano_material_invalido(app):
    assert chamar(app, "GET", "/api/plano?material=zzz").status == 400


def test_envio_de_duas_fotos_grava_na_pasta_de_entrada(enviar, dados):
    r = enviar(fotos=[("a.jpg", foto((1, 2, 3))), ("b.png", foto((9, 9, 9), "PNG"))])
    d = r.json()
    assert [a["situacao"] for a in d["arquivos"]] == ["recebido", "recebido"]
    gravados = sorted(p.name for p in (dados / "estudos" / "inbox" / "ABC1").iterdir())
    assert len(gravados) == 2
    assert all(len(n.split(".")[0]) == 64 for n in gravados)  # nome é o hash do conteúdo
    assert "a.jpg" not in gravados


def test_envio_repetido_e_reconhecido(enviar, dados):
    conteudo = foto((5, 5, 5))
    import hashlib

    estado.registrar_arquivo(hashlib.sha256(conteudo).hexdigest(), "x.jpg", "ABC1")
    d = enviar(fotos=[("a.jpg", conteudo)]).json()
    assert d["arquivos"][0]["situacao"] == "ja_estava"


def test_arquivo_texto_com_extensao_jpg_e_recusado(enviar):
    d = enviar(fotos=[("a.jpg", b"isto nao e imagem")]).json()
    assert d["arquivos"][0]["situacao"] == "recusado"


def test_foto_acima_do_limite_e_recusada(enviar, monkeypatch):
    monkeypatch.setattr("ui.servico.MAX_FOTO_BYTES", 100)
    d = enviar(fotos=[("a.jpg", foto())]).json()
    assert d["arquivos"][0]["situacao"] == "recusado"


def test_envio_acima_da_quantidade_e_recusado(enviar, monkeypatch):
    monkeypatch.setattr("ui.servico.MAX_FOTOS_POR_ENVIO", 1)
    r = enviar(fotos=[("a.jpg", foto((1, 1, 1))), ("b.jpg", foto((2, 2, 2)))])
    assert r.status == 400 and r.json()["erro"] == "fotos_demais"


def test_webp_e_heic_sao_recusados_com_mensagem(enviar):
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 "
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    d = enviar(fotos=[("a.webp", webp), ("b.heic", heic)]).json()
    assert "WebP" in d["arquivos"][0]["motivo"]
    assert "HEIC" in d["arquivos"][1]["motivo"]


def test_disciplina_com_barra_e_recusada(enviar):
    for nome in ("../x", "a/b", "", "a b", "x" * 40):
        assert enviar(disciplina=nome).status == 400


def test_nome_com_barra_e_pontos_nao_sai_da_pasta(enviar, dados):
    enviar(fotos=[("../../fuga.jpg", foto())])
    assert not (dados.parent / "fuga.jpg").exists()
    assert not (dados / "fuga.jpg").exists()


def test_link_simbolico_para_fora_e_recusado(dados, tmp_path):
    import pytest

    from ui.seguranca import PedidoRecusado, dentro_da_pasta

    fora = tmp_path / "fora"
    fora.mkdir()
    (dados / "elo").symlink_to(fora)
    with pytest.raises(PedidoRecusado):
        dentro_da_pasta(dados / "elo" / "x.jpg", dados)


def test_remover_move_para_a_lixeira(enviar, app, dados):
    d = enviar().json()
    envio, arq = d["envio_id"], d["arquivos"][0]["arquivo_id"]
    r = chamar(app, "DELETE", f"/api/materiais/{envio}/{arq}")
    assert r.status == 200
    assert not list((dados / "estudos" / "inbox" / "ABC1").iterdir())
    assert len(list((dados / "estudos" / "trash").iterdir())) == 1


def test_estimativa_sem_historico_devolve_nulo_e_origem(enviar, app):
    envio = enviar().json()["envio_id"]
    d = chamar(app, "POST", "/api/estimativa", {"envio_id": envio, "etapas": ["leitura"]}).json()
    linha = d["etapas"][0]
    assert linha["custo_usd"] is None and linha["origem"] == "sem_historico"
    assert d["total_incompleto"] is True


def _eventos(dados, n_jobs, agentes, custo=0.1):
    from core.config import get_settings

    logs = get_settings().logs_dir
    with open(logs / "2026-01-01.jsonl", "w") as f:
        for i in range(n_jobs):
            for agente in agentes:
                f.write(
                    json.dumps(
                        {
                            "job": f"j{i}",
                            "passo": f"{agente}:1",
                            "custo_usd": custo * (i + 1),
                            "duracao_ms": 2000,
                        }
                    )
                    + "\n"
                )


def test_estimativa_com_historico_devolve_mediana_e_n(enviar, app, dados):
    _eventos(dados, 3, ["triagem"], custo=0.1)  # por job: 0.1, 0.2, 0.3
    envio = enviar().json()["envio_id"]
    d = chamar(app, "POST", "/api/estimativa", {"envio_id": envio, "etapas": ["leitura"]}).json()
    linha = d["etapas"][0]
    assert linha["origem"] == "historico" and linha["n"] == 3
    assert abs(linha["custo_usd"] - 0.2) < 1e-9
    assert linha["espera_s"] == 2.0


def test_estimativa_de_etapa_guardada_e_zero(enviar, app, dados):
    conteudo = foto((7, 7, 7))
    import hashlib

    sha = hashlib.sha256(conteudo).hexdigest()
    job = estado.criar_job("aula", "ABC1", "2026-01-01")
    estado.registrar_arquivo(sha, "x.jpg", "ABC1", job_id=job)
    estado.transicionar(job, "rodando")
    estado.transicionar(job, "concluido")
    envio = enviar(fotos=[("a.jpg", conteudo)]).json()["envio_id"]
    d = chamar(
        app, "POST", "/api/estimativa", {"envio_id": envio, "etapas": ["leitura", "nota"]}
    ).json()
    assert all(e["origem"] == "guardado" and e["custo_usd"] == 0 for e in d["etapas"])
    assert d["tudo_guardado"] is True


def test_dependencia_faltante_e_recusada_pela_api(enviar, app):
    envio = enviar().json()["envio_id"]
    r = chamar(app, "POST", "/api/estimativa", {"envio_id": envio, "etapas": ["flashcards"]})
    assert r.status == 400 and r.json()["erro"] == "dependencia_faltante"


def test_processar_sem_confirmado_e_recusado(enviar, app):
    envio = enviar().json()["envio_id"]
    r = chamar(app, "POST", "/api/processar", {"envio_id": envio, "etapas": ["leitura"]})
    assert r.status == 400 and r.json()["erro"] == "confirmacao_ausente"
    r = chamar(
        app,
        "POST",
        "/api/processar",
        {"envio_id": envio, "etapas": ["leitura"], "confirmado": "sim"},
    )
    assert r.status == 400


def test_processar_acima_do_limite_e_bloqueado(enviar, app, monkeypatch):
    estado.registrar_custo_lancamento("j", "p", "m", 1, 1, 999.0)
    chamadas = []
    monkeypatch.setattr("ui.servico.drenar_fila", lambda **k: chamadas.append(k))
    envio = enviar().json()["envio_id"]
    r = chamar(
        app,
        "POST",
        "/api/processar",
        {"envio_id": envio, "etapas": ["leitura"], "confirmado": True},
    )
    assert r.status == 402
    assert chamadas == []


def test_recursos_em_desenvolvimento_respondem_404(app):
    for rota, metodo in (
        ("/api/duvidas", "POST"),
        ("/api/duvidas/aprovar", "POST"),
        ("/api/economia", "GET"),
    ):
        assert chamar(app, metodo, rota, {}).status == 404


def test_segunda_execucao_simultanea_recebe_409(enviar, app):
    envio = enviar().json()["envio_id"]
    app.servico._execucoes["x"] = {"fim": False}
    r = chamar(
        app,
        "POST",
        "/api/processar",
        {"envio_id": envio, "etapas": ["leitura"], "confirmado": True},
    )
    assert r.status == 409


def test_sem_nota_baixar_responde_404(app):
    job = estado.criar_job("aula", "ABC1", "2026-01-01")
    assert chamar(app, "GET", f"/api/notas/{job}/baixar").status == 404


def test_baixar_nota_devolve_anexo_markdown(app, dados):
    from projetos.estudos.manifesto import registrar_nota_manifesto

    job = estado.criar_job("aula", "ABC1", "2026-01-01")
    nota = dados / "estudos" / "output" / "ABC1" / "aula.md"
    nota.parent.mkdir(parents=True)
    nota.write_text("# Aula\n<script>alert(1)</script>", encoding="utf-8")
    registrar_nota_manifesto(
        job, nota, "concluido", [], "2026-01-01", duvidas=["d1"], possivel_injecao=True
    )
    r = chamar(app, "GET", f"/api/notas/{job}/baixar")
    assert r.status == 200
    assert r.cabecalhos["Content-Disposition"].startswith("attachment")
    d = chamar(app, "GET", f"/api/notas/{job}")
    assert d.cabecalhos["Content-Type"].startswith("application/json")
    assert "<script>alert(1)</script>" in d.json()["texto"]
    assert d.json()["avisos"]["possivel_injecao"] is True
    lista = chamar(app, "GET", "/api/notas").json()["notas"]
    assert lista[0]["avisos"] == 1


# ------------------------------------------------------------------ segurança
def test_host_diferente_de_loopback_e_recusado():
    import pytest

    from ui.servidor import servir

    with pytest.raises(ValueError):
        servir(host="0.0.0.0")


def test_host_externo_recebe_403(app):
    assert chamar(app, "GET", "/api/estado", host="evil.com").status == 403


def test_origin_externo_recebe_403(app):
    r = chamar(app, "GET", "/api/estado", cabecalhos={"Origin": "http://evil.com"})
    assert r.status == 403
    r = chamar(app, "GET", "/api/estado", cabecalhos={"Origin": "http://localhost:8765"})
    assert r.status == 200


def test_post_sem_token_recebe_403(app):
    assert chamar(app, "POST", "/api/estimativa", {}, token=None).status == 403


def test_post_com_token_errado_recebe_403(app):
    assert chamar(app, "POST", "/api/estimativa", {}, token="errado").status == 403


def test_bearer_certo_passa_errado_recebe_401_sem_variavel_desligado(app, monkeypatch):
    h = {"Authorization": "Bearer segredo"}
    assert chamar(app, "POST", "/api/estimativa", {}, token=None, cabecalhos=h).status == 401
    monkeypatch.setenv("CLASS2MD_API_TOKEN", "segredo")
    assert chamar(app, "POST", "/api/estimativa", {}, token=None, cabecalhos=h).status == 400
    h = {"Authorization": "Bearer outro"}
    assert chamar(app, "POST", "/api/estimativa", {}, token=None, cabecalhos=h).status == 401


def test_cabecalhos_de_seguranca(app):
    r = chamar(app, "GET", "/")
    assert "default-src 'self'" in r.cabecalhos["Content-Security-Policy"]
    assert r.cabecalhos["X-Content-Type-Options"] == "nosniff"


def test_chave_nao_aparece_em_nenhuma_resposta_nem_no_log(app, enviar, dados):
    respostas = [
        chamar(app, "GET", "/"),
        chamar(app, "GET", "/api/estado"),
        chamar(app, "GET", "/api/plano?material=foto_aula"),
        chamar(app, "GET", "/api/notas"),
        chamar(app, "GET", "/api/jobs/00000000"),
        chamar(app, "POST", "/api/processar", {}),
        chamar(app, "POST", "/api/estimativa", b"{nao json"),
        enviar(),
    ]
    for r in respostas:
        assert CHAVE_DE_TESTE not in r.texto
    from core.config import get_settings

    for log in get_settings().logs_dir.glob("*.jsonl"):
        assert CHAVE_DE_TESTE not in log.read_text()


def test_erro_interno_nao_devolve_rastro_de_pilha(app, monkeypatch):
    def quebra(self):
        raise RuntimeError(f"falha com {CHAVE_DE_TESTE}")

    monkeypatch.setattr("ui.servico.Servico.estado", quebra)
    r = chamar(app, "GET", "/api/estado")
    assert r.status == 500
    assert "Traceback" not in r.texto and CHAVE_DE_TESTE not in r.texto


def test_nenhuma_rota_aceita_caminho_de_destino():
    import re
    from pathlib import Path

    fonte = (Path(__file__).parents[2] / "ui" / "app.py").read_text()
    assert not re.search(r"\b(destino|caminho|path|pasta)=", fonte.replace("caminho = ", ""))
    assert 'environ.get("QUERY_STRING"' in fonte  # só consulta: material


def test_ui_nao_importa_anthropic_nem_le_env():
    from pathlib import Path

    for arquivo in (Path(__file__).parents[2] / "ui").glob("*.py"):
        texto = arquivo.read_text()
        assert "import anthropic" not in texto and "from anthropic" not in texto
        assert "dotenv" not in texto and '.env"' not in texto
