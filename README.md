# Suporte Omnis

Agente que lê a caixa **suporte@dataomnis.com.br** a cada 10 minutos, responde sozinho
as dúvidas simples e encaminha as complexas para a equipe. Todos os atendimentos ficam
registrados em PostgreSQL, com as dúvidas interessantes marcadas para análise.

## Como funciona

```
          a cada 10 min
Outlook ─────────────────► Azure Function ──► Claude: triagem
(suporte@)                        │
                                  ├─ simples + documentado ──► responde o cliente no mesmo email
                                  ├─ complexo ───────────────► encaminha para a equipe
                                  │                            (Responder vai direto ao cliente)
                                  │                            e avisa o cliente com o nº do chamado
                                  ├─ automático / spam ──────► ignora
                                  └─ tudo ───────────────────► PostgreSQL (tabela tickets)
```

| Tipo de dúvida | O que o agente faz |
|---|---|
| Login, erro de login, senha, uso de funcionalidade | Responde, se a resposta estiver na base de conhecimento |
| Conexão com banco, criação de agente, departamento ou grupo, governança | Encaminha para a equipe |
| Bug, lentidão, pedido de melhoria | Encaminha e marca como dúvida interessante |
| Cliente respondeu de novo no mesmo assunto | Encaminha para a equipe |
| Resposta automática, remetente interno, spam | Ignora |

Regras de segurança do atendimento:

- **Na dúvida, encaminha.** Baixa confiança, falta de informação na base ou qualquer erro
  levam o email para a equipe.
- **O agente nunca envia nem redefine senhas.** Ele só orienta o processo de recuperação.
- **Nenhum email se perde.** Falhas são tentadas de novo até 3 vezes. Depois disso, o
  email vai para a equipe sem passar pela IA.
- **Emails abertos por alguém no Outlook também são atendidos.** O agente olha tudo que
  chegou nas últimas 24 horas e usa o banco para nunca atender o mesmo email duas vezes.
- **Cada email recebe uma categoria no Outlook**, como "Agente Omnis: respondido", para
  a equipe ver o que foi feito.

## Estrutura

```
function_app.py            gatilho do Azure Functions (a cada 10 minutos)
omnis_support/
  app.py                   monta o agente com as dependências reais
  config.py                configuração via variáveis de ambiente
  domain.py                categorias, status e modelos do atendimento
  services/
    support_agent.py       orquestra o ciclo: ler, classificar, agir, registrar
    decision.py            regras de negócio (funções puras)
    ports.py               contratos da infraestrutura
  ai/                      triagem e redação de respostas com o Claude
  email/                   Microsoft Graph, filtros, modelos HTML, modo simulação
  db/                      repositório PostgreSQL e migrações SQL
knowledge/                 base de conhecimento usada nas respostas
infra/main.bicep           infraestrutura do Azure
scripts/                   registro na Graph, deploy e integração com GitHub
tests/                     testes automatizados
```

## Rodar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # preencha os valores
python -m omnis_support     # executa um ciclo
```

Com `DRY_RUN=true` no `.env`, o agente lê e classifica os emails reais, mas só mostra
no terminal o que faria. Nada é enviado, marcado como lido ou gravado no banco.

Para testar com banco local, suba o PostgreSQL com `docker compose up -d` e aplique as
migrações com `python -m omnis_support migrate`.

## Qualidade

```powershell
ruff check .           # lint
ruff format .          # formatação
mypy                   # tipos (modo estrito)
pytest                 # testes
```

O GitHub Actions roda tudo isso a cada push e pull request.

## Consultas úteis no banco

```sql
SELECT * FROM vw_duvidas_interessantes;     -- dúvidas marcadas como interessantes
SELECT * FROM vw_resumo_por_categoria;      -- volume semanal por categoria
SELECT * FROM tickets WHERE status = 'erro';
```

## Deploy

Veja [docs/DEPLOY.md](docs/DEPLOY.md).
