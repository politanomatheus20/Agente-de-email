# Base de conhecimento do agente

O agente só responde sozinho o que estiver documentado nesta pasta.
Tudo que não estiver aqui é encaminhado para a equipe.

## Como funciona

- Cada arquivo `.md` desta pasta é lido pelo agente, em ordem alfabética.
- Este `README.md` é ignorado.
- **Arquivos que ainda contêm o marcador `[PREENCHER]` são ignorados.** Assim o agente
  nunca responde com informação provisória. Remova todos os marcadores de um arquivo
  para ativá-lo.
- Depois de editar, faça o deploy de novo para o agente usar a versão nova.

## Como escrever bem

- Escreva como se estivesse explicando para um cliente: passo a passo, com o nome exato
  dos botões e menus.
- Inclua links reais, como o da página de recuperação de senha.
- Descreva as mensagens de erro exatamente como aparecem na tela e a solução de cada uma.
- Diga também o que **não** pode ser resolvido pelo cliente, para o agente saber quando
  encaminhar.
- Um assunto por arquivo facilita a manutenção.
