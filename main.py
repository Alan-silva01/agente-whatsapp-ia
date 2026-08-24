import os
import uvicorn
import httpx
import asyncio
import base64
from typing import Dict, Any, List
from fastapi import FastAPI, Request, BackgroundTasks
from database import obter_ou_criar_cliente
from agent import processar_mensagem_agente, client as openai_client
from evolution import enviar_mensagem_whatsapp, enviar_mensagens_fracionadas_com_digitacao

app = FastAPI(title="Agente WhatsApp - Odonto Clínica Londrina")

# Dicionário global para controlar o buffer de 15 segundos por telefone
BUFFER_MENSAGENS: Dict[str, Dict[str, Any]] = {}


def extrair_dados_mensagem(payload: dict):
    """
    Extrai remoteJid, pushName, texto ou mídias (áudio/imagem) do payload da Evolution API,
    além de verificar se o paciente citou/respondeu uma mensagem específica (quotedMessage).
    """
    try:
        data = payload.get("data", payload)
        key = data.get("key", {})
        
        from_me = key.get("fromMe", False)
        remote_jid = key.get("remoteJid", "")
        
        # Ignora mensagens enviadas pelo próprio robô ou de grupos
        if from_me or not remote_jid or "@g.us" in remote_jid:
            return None
        
        # Limpa o número de telefone (remove @s.whatsapp.net)
        telefone = remote_jid.split("@")[0]
        push_name = data.get("pushName", "Desconhecido")
        
        # Extrai o texto ou mídias da mensagem
        message_obj = data.get("message", {})
        texto = ""
        
        if "conversation" in message_obj:
            texto = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            texto = message_obj["extendedTextMessage"].get("text", "")
        elif "imageMessage" in message_obj:
            caption = message_obj["imageMessage"].get("caption", "")
            texto = f"[O paciente enviou uma imagem/foto. Legenda: {caption}]" if caption else "[O paciente enviou uma foto/imagem para avaliação]"
        elif "audioMessage" in message_obj:
            audio_obj = message_obj["audioMessage"]
            base64_str = audio_obj.get("base64") or data.get("base64") or message_obj.get("base64")
            audio_url = audio_obj.get("url")
            if base64_str:
                texto = f"[AUDIO_BASE64:{base64_str}]"
            elif audio_url:
                texto = f"[AUDIO_URL:{audio_url}]"
            else:
                texto = "[O paciente enviou um áudio de voz]"
        elif isinstance(message_obj, str):
            texto = message_obj
            
        if not texto:
            return None

        # Extrai mensagem citada/mencionada (quotedMessage) se existir
        context_info = None
        if "extendedTextMessage" in message_obj and isinstance(message_obj["extendedTextMessage"], dict):
            context_info = message_obj["extendedTextMessage"].get("contextInfo")
        elif "contextInfo" in message_obj:
            context_info = message_obj.get("contextInfo")
            
        if context_info and isinstance(context_info, dict):
            quoted_msg = context_info.get("quotedMessage")
            if quoted_msg and isinstance(quoted_msg, dict):
                texto_citado = ""
                if "conversation" in quoted_msg:
                    texto_citado = quoted_msg["conversation"]
                elif "extendedTextMessage" in quoted_msg:
                    texto_citado = quoted_msg["extendedTextMessage"].get("text", "")
                elif "imageMessage" in quoted_msg:
                    caption = quoted_msg["imageMessage"].get("caption", "")
                    texto_citado = f"[Imagem: {caption}]" if caption else "[Imagem]"
                elif "audioMessage" in quoted_msg:
                    texto_citado = "[Áudio de voz]"
                
                if texto_citado:
                    texto = f'[Em resposta à mensagem citada pelo paciente: "{texto_citado}"]\n{texto}'
            
        return {
            "telefone": telefone,
            "push_name": push_name,
            "texto": texto
        }
    except Exception as e:
        print(f"⚠️ Erro ao extrair payload da Evolution API: {e}")
        return None


def adicionar_ao_buffer(dados: dict):
    """
    Adiciona a mensagem recebida ao buffer de 15 segundos do telefone e reinicia o timer.
    """
    telefone = dados["telefone"]
    push_name = dados["push_name"]
    texto = dados["texto"]
    
    if telefone in BUFFER_MENSAGENS:
        info = BUFFER_MENSAGENS[telefone]
        info["mensagens"].append(texto)
        if push_name and push_name != "Desconhecido":
            info["push_name"] = push_name
        if info.get("task"):
            info["task"].cancel()
    else:
        BUFFER_MENSAGENS[telefone] = {
            "push_name": push_name,
            "mensagens": [texto],
            "task": None
        }
        
    task = asyncio.create_task(aguardar_e_processar_buffer(telefone, delay_segundos=15.0))
    BUFFER_MENSAGENS[telefone]["task"] = task


async def aguardar_e_processar_buffer(telefone: str, delay_segundos: float = 15.0):
    """
    Aguarda 15 segundos. Se nenhuma nova mensagem for recebida nesse intervalo,
    agrupa todas as mensagens acumuladas e envia para a IA responder de uma só vez.
    """
    try:
        await asyncio.sleep(delay_segundos)
    except asyncio.CancelledError:
        # Timer cancelado pois uma nova mensagem chegou dentro dos 15 segundos
        return

    dados_buffer = BUFFER_MENSAGENS.pop(telefone, None)
    if not dados_buffer or not dados_buffer.get("mensagens"):
        return

    push_name = dados_buffer["push_name"]
    mensagens_raw = dados_buffer["mensagens"]

    # Processa áudios pendentes (via Base64 ou URL)
    mensagens_processadas: List[str] = []
    for msg in mensagens_raw:
        if msg.startswith("[AUDIO_BASE64:") and msg.endswith("]"):
            base64_data = msg[14:-1]
            print(f"🎙️ Transcrevendo áudio via Base64 no Whisper...")
            try:
                temp_path = f"/tmp/audio_{telefone}.ogg"
                audio_bytes = base64.b64decode(base64_data)
                with open(temp_path, "wb") as f:
                    f.write(audio_bytes)
                
                if openai_client:
                    with open(temp_path, "rb") as audio_file:
                        transcription = openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )
                        msg = transcription.text
                        print(f"🎙️ Áudio transcrito com sucesso: '{msg}'")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"❌ Erro ao transcrever áudio em Base64: {e}")
                msg = "[Áudio do paciente que não pôde ser transcrito com clareza]"

        elif msg.startswith("[AUDIO_URL:") and msg.endswith("]"):
            audio_url = msg[11:-1]
            print(f"🎙️ Baixando áudio para transcrição no Whisper: {audio_url}")
            try:
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    res = await http_client.get(audio_url)
                    if res.status_code == 200:
                        temp_path = f"/tmp/audio_{telefone}.ogg"
                        with open(temp_path, "wb") as f:
                            f.write(res.content)
                        
                        if openai_client:
                            with open(temp_path, "rb") as audio_file:
                                transcription = openai_client.audio.transcriptions.create(
                                    model="whisper-1",
                                    file=audio_file
                                )
                                msg = transcription.text
                                print(f"🎙️ Áudio transcrito com sucesso: '{msg}'")
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
            except Exception as e:
                print(f"❌ Erro ao transcrever áudio via Whisper: {e}")
                msg = "[Áudio do paciente que não pôde ser transcrito com clareza]"
        mensagens_processadas.append(msg)

    if len(mensagens_processadas) == 1:
        texto_final = mensagens_processadas[0]
    else:
        texto_final = "\n".join(mensagens_processadas)

    print(f"\n📩 [BUFFER 15s EXSPIRADO] Processando {len(mensagens_processadas)} mensagem(ns) agrupada(s) de {telefone} ({push_name}):\n'{texto_final}'")

    # 1. Busca ou cria o cliente no Supabase
    cliente = obter_ou_criar_cliente(telefone=telefone, push_name=push_name)

    # 2. Executa o agente da Bianca
    resposta_agente = await processar_mensagem_agente(cliente=cliente, texto_usuario=texto_final)

    # 3. Envia resposta fracionada em mensagens curtas com status "digitando..."
    await enviar_mensagens_fracionadas_com_digitacao(telefone=telefone, texto=resposta_agente)



@app.post("/webhook")
async def webhook_whatsapp(request: Request):
    """
    Endpoint chamado pela Evolution API via Webhook.
    """
    try:
        payload = await request.json()
        dados = extrair_dados_mensagem(payload)
        
        if dados:
            adicionar_ao_buffer(dados)
            return {
                "status": "bufferizado",
                "mensagem": "Mensagem adicionada ao buffer de 15 segundos",
                "telefone": dados["telefone"]
            }
        
        return {"status": "ignorado", "motivo": "Mensagem do próprio bot, de grupo ou vazia."}
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return {"status": "erro", "detalhe": str(e)}


@app.get("/")
def home():
    return {"status": "ok", "mensagem": "Agente WhatsApp rodando com sucesso!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


