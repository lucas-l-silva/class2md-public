# Segurança

## Como reportar

Abra uma issue privada de segurança no repositório (aba Security, "Report a vulnerability")
ou escreva ao mantenedor pelo contato do perfil do GitHub. Não publique detalhes de uma
falha antes de ela ser corrigida.

## O que o projeto faz com chaves e dados

- A chave da API fica só no seu computador, em `.env` ou em `~/agent-secrets/estudos.env`.
  Esses arquivos estão no `.gitignore`. O projeto nunca escreve a chave em log, nota ou cache.
- As fotos e os PDFs são enviados à API da Anthropic para serem lidos. Não processe material
  que você não pode enviar a um serviço externo.
- Todo texto vindo de foto ou PDF é tratado como dado, nunca como instrução ao modelo.
- Nenhuma nota é gravada direto no seu cofre do Obsidian. As notas saem em uma pasta de
  staging e você decide o que promover.

## Interface local

A interface (`scripts/estudos.py ui`) escuta só em `127.0.0.1`, nunca em outra interface de rede.
Não a exponha à internet nem a coloque atrás de um proxy público.

## Dependências

Mantenha o `uv.lock` atualizado e rode `uv run pip-audit` (ou equivalente) antes de publicar
uma versão.
