# Retry automático de criação da Oracle A1 (6 GB)

Use este recurso apenas depois de autorizar explicitamente a criação automática
da VM. Ele tenta criar uma `VM.Standard.A1.Flex` gratuita com **1 OCPU e 6 GB**
a cada 15 minutos, até a Oracle disponibilizar uma instância utilizável.

O retry usa a subnet pública `rsi-radar-public-subnet`, a imagem Oracle Linux 9
mais recente compatível com A1 e a chave pública SSH
`%USERPROFILE%\.ssh\rsi_radar_oracle_ed25519.pub`. O domínio de falha não é
enviado, permitindo que a Oracle escolha o melhor disponível.

## Proteções

- não exclui nem modifica VMs existentes;
- interrompe a criação se já houver qualquer A1 ativa na conta, evitando duas
  VMs A1 sem uma nova decisão manual;
- percorre todas as páginas de instâncias ao fazer essa verificação;
- usa um lock local para evitar duas execuções simultâneas;
- grava e reutiliza um token de idempotência antes de enviar a criação, para que
  uma queda de conexão não resulte em duas VMs;
- mantém a tarefa ativa enquanto a nova VM estiver em `PROVISIONING` e só a
  desativa quando a instância deixar esse estado transitório;
- interrompe a tarefa quando encontra uma configuração inválida que exige
  correção manual, em vez de repetir esse erro indefinidamente;
- registra o resultado, sem segredos, em
  `%LOCALAPPDATA%\RsiRadar\oracle-a1-provision-retry-state.json` e `.log`.
  O arquivo de log preserva apenas a parte mais recente para não crescer sem
  limite.

## Validar sem criar nada

```powershell
.\.venv\Scripts\python.exe .\tools\oracle_a1_provision_retry.py --dry-run
```

## Ativar a repetição a cada 15 minutos

```powershell
.\tools\install_oracle_a1_provision_retry.ps1 -IntervalMinutes 15
```

Ela funciona enquanto o computador estiver ligado e o usuário do Windows estiver
conectado. Para acompanhar:

```powershell
Get-ScheduledTask -TaskName 'RSI Radar - Provisionar Oracle A1 6GB' |
  Get-ScheduledTaskInfo
Get-Content "$env:LOCALAPPDATA\RsiRadar\oracle-a1-provision-retry.log" -Tail 20
```

Após o resultado `LAUNCH_ACCEPTED`, a A1 estará em `PROVISIONING`. A tarefa faz
uma nova checagem no próximo ciclo e se desativa quando confirmar que a VM saiu
desse estado; aguarde `RUNNING` antes de iniciar o deploy do projeto.
