# Tradie AI Receptionist — Python Setup Guide

## File Structure

```
tradie-ai-agent-python/
├── server.py              # Main FastAPI webhook server
├── prompts.py             # AI agent system prompt builder
├── sms.py                 # Twilio SMS notification service
├── tradies.json           # Multi-tradie configuration
├── requirements.txt       # Python dependencies
├── Procfile               # Railway deployment config
├── runtime.txt            # Python version for Railway
├── .env.example           # Environment variables template
└── logs/
    └── calls.log          # Call log file
```

## Local Setup

```bash
# Make sure you have Python 3.10+ installed
python3 --version

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Mac/Linux
# or: venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your keys
cp .env.example .env

# Run locally
python server.py
```

Server runs at http://localhost:3000

## Deploy to Railway

```bash
# Install Railway CLI
# Mac:
brew install railway
# Or via npm:
npm i -g @railway/cli

# Login
railway login

# Create project
railway init

# Deploy
railway up

# Set environment variables
railway variables set VAPI_API_KEY=your_key
railway variables set TWILIO_ACCOUNT_SID=your_sid
railway variables set TWILIO_AUTH_TOKEN=your_token
railway variables set TWILIO_SMS_FROM=+61xxxxxxxxx
railway variables set WEBHOOK_SECRET=any-random-string
```

## IMPORTANT: Update Your Voice ID

Open `server.py`, find this line (around line 112):
```python
"voiceId": "pFZP5JQG7iQjIQuC4Bku",  # REPLACE with your ElevenLabs Voice ID
```
Replace with your actual ElevenLabs Voice ID (Sharon's ID).

## After Deployment

1. Copy your Railway URL (e.g. `https://xxx.up.railway.app`)
2. In Vapi → Phone Numbers → Import your Twilio number
3. Set Server URL to: `https://your-railway-url/webhook/vapi`
4. Update `tradies.json` with real tradie details + Vapi Phone Number ID
5. Redeploy: `railway up`
6. Test by calling the number!

## Cost Breakdown Per Tradie

| Service | Monthly Cost |
|---------|-------------|
| Vapi.ai (voice AI) | ~$20–30 |
| Twilio (number + SMS) | ~$5–15 |
| OpenAI (via Vapi) | ~$3–8 |
| Railway hosting (shared) | ~$2–3 |
| **Total** | **~$35–55** |
| **You charge** | **$200** |
| **Profit** | **~$145–165** |
