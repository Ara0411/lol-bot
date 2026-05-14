# 🚀 배포 가이드 (Oracle Cloud Free Tier)

## 📌 중요 파일 위치 (절대 잃어버리지 마세요!)

| 파일 | 위치 |
|------|------|
| SSH 키 (Windows) | `C:\Users\Twomans\Downloads\ssh-key-2026-05-14.key` |
| SSH 키 (WSL) | `~/.ssh/oracle-discord-bot.key` |
| 봇 코드 (Oracle) | `/home/ubuntu/discord-scrim-bot/` |
| 봇 .env (Oracle) | `/home/ubuntu/discord-scrim-bot/.env` |

> ⚠️ Windows의 SSH 키 파일은 **절대 지우지 마세요**. 잃어버리면 VM 접속 불가 (재발급 불가).

---

## 🔌 봇 관리 명령어 (WSL 터미널에서)

### 상태 확인
```bash
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 'sudo systemctl status discord-bot'
```

### 실시간 로그
```bash
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 'sudo journalctl -u discord-bot -f'
```

### 재시작 (코드 수정 후)
```bash
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 'sudo systemctl restart discord-bot'
```

### 정지 / 시작
```bash
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 'sudo systemctl stop discord-bot'
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 'sudo systemctl start discord-bot'
```

### 코드 업데이트 (GitHub 푸시 후)
```bash
ssh -i ~/.ssh/oracle-discord-bot.key ubuntu@168.110.103.112 \
  'cd /tmp/lol-bot-src && git pull && cp -r scrim-bot/* ~/discord-scrim-bot/ && sudo systemctl restart discord-bot'
```

---

## ⚙️ 인프라 정보

| 항목 | 값 |
|------|-----|
| 클라우드 | Oracle Cloud Infrastructure (OCI) |
| 리전 | 춘천 (ap-chuncheon-1) |
| VM 이름 | discord-bot |
| Shape | VM.Standard.E2.1.Micro (1 OCPU, 1 GB RAM) |
| OS | Ubuntu 22.04 LTS |
| Public IP | 168.110.103.112 (Ephemeral) |
| 서비스명 | `discord-bot.service` (systemd) |
| 자동 재시작 | 죽으면 10초 후 (Restart=always) |
| 부팅 시 자동 시작 | enabled |

---

## 💰 비용

**VM.Standard.E2.1.Micro = Oracle "Always Free" 리소스 → 평생 무료**

- 자동 결제 절대 안 됨 (사용자가 "Upgrade to Pay-as-you-go" 수동 클릭 안 하는 한)
- Free Trial 크레딧 ($300, 30일) 만료되면 자동으로 Always Free 한도로 다운그레이드
- E2.1.Micro 인스턴스 1~2개 + 200GB Block Storage + 10TB/월 outbound 모두 Always Free 포함

### 안전장치 (옵션)
- 카드 한도 낮은 카드로 등록 (체크카드 등)
- Budget alert 설정 (Console → Billing → Budgets)
- 절대 "Upgrade" 버튼 누르지 않기
