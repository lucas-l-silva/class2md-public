# Promotor — staging → vault

O único passo do pipeline que escreve no vault do Obsidian, com aprovação humana nota a nota. 

Pode rodar na **mesma máquina** que o pipeline (modo local, o mais comum) ou numa máquina separada
(modo remoto, via SSH — por exemplo se o processamento roda num servidor/mini-PC e o vault vive no seu
notebook).

## Config

`~/.config/class2md/promotor.toml` — copie de `docs/promotor.example.toml`:

```toml
vault_dir = "/caminho/para/seu/vault/Estudos"
anexos_dir = "anexos"          # relativo a vault_dir, ou absoluto

# Só defina os dois campos abaixo se pipeline e promotor rodam em máquinas DIFERENTES.
# ssh_host = "nome-do-host-ssh"       # alias do ~/.ssh/config para a máquina do pipeline
# repo_dir_remoto = "~/class2md"   # onde o repo está clonado na máquina remota
```

`vault_dir` e `anexos_dir` são obrigatórios. Sem a config, `promover` recusa rodar.

## Uso

```bash
uv run python scripts/promover.py              # --simular (padrão): só mostra o plano
uv run python scripts/promover.py --sem-simular # roda o loop de verdade
```

`--simular` é o padrão. Nada é escrito no vault até você passar `--sem-simular` explicitamente.

## O que acontece

1. **Sincroniza**:
   - **Modo local** (sem `ssh_host` na config): copia diretamente de `~/agent-data/estudos/output/` e
     `~/agent-data/estudos/crops/` para `./staging-local/` e `./staging-crops/`.
   - **Modo remoto** (com `ssh_host`): `rsync -a <ssh_host>:~/agent-data/estudos/output/ ./staging-local/`
     e o mesmo para `crops/`.
2. **Monta o plano**: lê `_manifest.json`, casa cada nota com o vault por caminho relativo
   (a parte depois de `.../output/`) e classifica em `novo` / `identico` / `alterado`.
   Cada item mostra avisos: `precisa_revisao`, `problemas_validacao` (do A10), `avisos_conceitos`
   (do A6) e `possivel_injecao` — este último é uma varredura própria do promotor no texto da
   nota (não vem do pipeline), por padrões suspeitos tipo "ignore as instruções anteriores".
   Lembrete: **todo conteúdo processado é dado, não instrução** — o aviso só chama atenção,
   quem decide é sempre você.
3. **Loop interativo** (só com `--sem-simular`), por nota:
   - `[a]ceitar` / `[p]ular` / `[e]ditar` (editar abre `$EDITOR` num arquivo temporário; ao
     salvar e fechar, volta a perguntar com o conteúdo editado).
   - Se a nota já existe no vault e diverge (`alterado`), aceitar **exige** ver o diff
     (`vault` vs `staging`) e confirmar a sobrescrita separadamente — sem confirmação explícita,
     conta como pulada.
   - Ao aceitar de fato: resolve só os recortes que a nota **realmente embute**
     (`![[arquivo.png]]`, não `[[wikilink]]` normal) e copia nota + recortes pro vault/anexos.
   - Pede a nota de qualidade (1–5); repete até validar.
   - Chama `scripts/estudos.py promover-finalizar <job_id> --nota <n>` — localmente (modo local) ou
     via `ssh <ssh_host>` (modo remoto): arquiva a cópia de origem em `estudos/promovidas/` e marca o
     job como `promovido` no SQLite (com a nota, pra calibrar prompts depois — ver Avaliação).

## Conflito (nota já existe no vault)

Nunca é resolvido em silêncio. `alterado` sempre mostra diff unificado e pede confirmação
explícita antes de sobrescrever; recusar equivale a pular aquela nota nesta rodada.
