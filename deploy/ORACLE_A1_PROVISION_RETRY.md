# Retry automático de criação da Oracle A1 (6 GB)

Use este recurso apenas depois de autorizar explicitamente a criação automática
da VM. Ele tenta criar uma `VM.Standard.A1.Flex` gratuita com **1 OCPU e 6 GB**
a cada 15 minutos, até a Oracle aceitar a solicitação.

O retry usa a subnet pública `rsi-radar-public-subnet`, a imagem Oracle Linux 9
mais recente compatível com A1 e a chave pública SSH
`%USERPROFILE%\.ssh\rsi_radar_oracle_ed25519.pub`. O domínio de falha não é
enviado, permitindo que a Oracle escolha o melhor disponível.

## Proteções

- não exclui nem modifica VMs existentes;
- não cria uma segunda A1 se já existir uma chamada `rsi-radar-api-6gb`;
- usa um lock local para evitar duas execuções simultâneas;
- desativa a tarefa agendada após a Oracle aceitar a criação;
- registra o resultado, sem segredos, em
  `%LOCALAPPDATA%\RsiRadar\oracle-a1-provision-retry-state.json` e `.log`.

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

Após o resultado `LAUNCH_ACCEPTED`, a A1 estará em `PROVISIONING`; aguarde o
estado `RUNNING` antes de iniciar o deploy do projeto.
