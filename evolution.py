import os
import re
import asyncio
import httpx
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")

async def obter_media_base64_evolution(message_id: str) -> Optional[str]:
    """
    Busca o conteúdo Base64 de uma mídia (áudio ou imagem) na Evolution API usando a rota /chat/findMediaBase64.
    """
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE or not message_id:
        return None
        
    url = f"{EVOLUTION_API_URL}/chat/findMediaBase64/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "message": {
            "key": {
                "id": message_id
            }
        },
        "convertToMp4": False
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                dados = res.json()
                b64 = dados.get("base64") or dados.get("media")
                if b64:
                    print(f"✅ Mídia recuperada com sucesso da Evolution API para mensagem {message_id}")
                    return b64
            print(f"⚠️ Evolution API findMediaBase64 retornou status {res.status_code} para {message_id}")
    except Exception as e:
        print(f"❌ Erro ao buscar mídia na Evolution API ({message_id}): {e}")
        
    return None


async def enviar_presenca_whatsapp(telefone: str, presenca: str = "composing", delay_ms: int = 1200) -> bool:

    """
    Envia o status de presença (ex: 'composing' para digitando...) via Evolution API.
    """
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE:
        return False
    
    url = f"{EVOLUTION_API_URL}/chat/sendPresence/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": telefone,
        "presence": presenca,
        "delay": delay_ms
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, headers=headers, json=payload)
            return True
    except Exception as e:
        print(f"⚠️ Erro ao enviar presença '{presenca}' na Evolution API: {e}")
        return False

async def enviar_mensagem_whatsapp(telefone: str, texto: str) -> bool:
    """
    Envia uma única mensagem de texto via Evolution API para o número do WhatsApp.
    """
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE:
        print(f"⚠️ Evolution API não configurada. Mensagem simulada enviada para {telefone}:\n-> {texto}")
        return False
    
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": telefone,
        "text": texto
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resposta = await client.post(url, headers=headers, json=payload)
            if resposta.status_code in [200, 201]:
                print(f"📲 Mensagem enviada com sucesso pro WhatsApp ({telefone}): '{texto}'")
                return True
            else:
                print(f"❌ Erro na Evolution API ({resposta.status_code}): {resposta.text}")
                return False
    except Exception as e:
        print(f"❌ Exceção ao conectar com a Evolution API: {e}")
        return False

def quebrar_mensagem_humana(texto: str) -> List[str]:
    """
    Quebra um texto longo em mensagens curtas, humanas e naturais para o WhatsApp.
    Dividido por quebras de linha e depois por frases curtas se necessário.
    """
    if not texto:
        return []
        
    linhas = [l.strip() for l in texto.split('\n') if l.strip()]
    partes: List[str] = []
    
    for linha in linhas:
        if len(linha) <= 120:
            partes.append(linha)
        else:
            subfrases = re.split(r'(?<=[.?!;])\s+', linha)
            acumulado = ""
            for sub in subfrases:
                sub = sub.strip()
                if not sub:
                    continue
                if len(acumulado) + len(sub) + 1 <= 120:
                    acumulado = f"{acumulado} {sub}".strip()
                else:
                    if acumulado:
                        partes.append(acumulado)
                    acumulado = sub
            if acumulado:
                partes.append(acumulado)
                
    return partes if partes else [texto]

async def enviar_mensagens_fracionadas_com_digitacao(telefone: str, texto: str):
    """
    Fraciona a resposta da IA em mensagens curtas humanas, simula o tempo de digitação ('composing')
    para cada fragmento proporcionalmente ao tamanho e envia em sequência.
    """
    mensagens = quebrar_mensagem_humana(texto)
    
    for i, msg in enumerate(mensagens):
        if not msg.strip():
            continue
            
        tempo_digitacao = max(1.2, min(5.5, len(msg) * 0.045))
        tempo_ms = int(tempo_digitacao * 1000)
        
        await enviar_presenca_whatsapp(telefone, presenca="composing", delay_ms=tempo_ms)
        
        print(f"⏳ Simulando digitação por {tempo_digitacao:.1f}s para ({telefone}): '{msg}'")
        await asyncio.sleep(tempo_digitacao)
        
        await enviar_mensagem_whatsapp(telefone, msg)
        
        if i < len(mensagens) - 1:
            await asyncio.sleep(0.6)

