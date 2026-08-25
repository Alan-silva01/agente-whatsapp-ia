import os
import re
import tempfile
import uvicorn
import httpx
import asyncio
import base64
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request, BackgroundTasks
import redis.asyncio as redis
from dotenv import load_dotenv
from database import obter_ou_criar_cliente, pausar_agente, agente_esta_pausado, processar_lembretes_2h_antes
from agent import processar_mensagem_agente, client as openai_client
from evolution import enviar_mensagem_whatsapp, enviar_mensagens_fracionadas_com_digitacao, obter_media_base64_evolution, EVOLUTION_API_KEY

load_dotenv()

app = FastAPI(title="Agente WhatsApp - Odonto Clínica Londrina")

# Configuração do Redis (Opcional - Buffer Distribuído com fallback para RAM)
REDIS_URL = os.getenv("REDIS_URL", "")
redis_client: Optional[redis.Redis] = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(
            REDIS_URL, 
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=3.0
        )
        print(f"🔴 Conexão Redis configurada em: {REDIS_URL}")
    except Exception as e:
        print(f"⚠️ Erro ao inicializar Redis ({e}). Usando buffer em memória RAM.")
        redis_client = None


# Dicionário global para controlar o buffer em memória (usado como fallback ou sem Redis)
BUFFER_MENSAGENS: Dict[str, Dict[str, Any]] = {}
TASKS_ATIVAS: Dict[str, asyncio.Task] = {}



def decodificar_base64_seguro(b64_str: str) -> bytes:
    """
    Decodifica strings em Base64 com segurança, corrigindo padding (=) e caracteres URL-safe (- e _)
    gerados pelo WhatsApp / Evolution API.
    """
    if not b64_str:
        return b""
    
    b64_clean = re.sub(r'\s+', '', b64_str)
    if b64_clean.startswith("data:"):
        if "," in b64_clean:
            b64_clean = b64_clean.split(",", 1)[1]
            
    b64_clean = b64_clean.replace('-', '+').replace('_', '/')
    missing_padding = len(b64_clean) % 4
    if missing_padding:
        b64_clean += '=' * (4 - missing_padding)
        
    return base64.b64decode(b64_clean)


def extrair_dados_mensagem(payload: dict):
    """
    Extrai remoteJid, pushName, texto ou mídias (áudio/imagem) do payload da Evolution API,
    além de verificar se o paciente citou/respondeu uma mensagem específica (quotedMessage).
    """
    try:
        data = payload.get("data", payload)
        key = data.get("key", {})
        message_id = key.get("id", "")
        
        from_me = key.get("fromMe", False)
        remote_jid = key.get("remoteJid", "")
        
        # Ignora mensagens de grupos ou sem remetente
        if not remote_jid or "@g.us" in remote_jid:
            return None
        
        # Limpa o número de telefone (remove @s.whatsapp.net)
        telefone = remote_jid.split("@")[0]
        push_name = data.get("pushName", "Desconhecido")

        # Se a mensagem foi enviada pelo próprio atendente humano (WhatsApp Web/Celular da clínica)
        if from_me:
            if telefone:
                pausar_agente(telefone, minutos=5)
                print(f"🛑 Mensagem enviada pelo atendente humano (fromMe=True) para {telefone}. IA pausada por 5 minutos.")
            return None
        
        # Extrai o texto ou mídias da mensagem (desembrulha se for efêmera/viewOnce)
        message_obj = data.get("message", {})
        if "ephemeralMessage" in message_obj:
            message_obj = message_obj["ephemeralMessage"].get("message", {})
        elif "viewOnceMessage" in message_obj:
            message_obj = message_obj["viewOnceMessage"].get("message", {})
        elif "documentWithCaptionMessage" in message_obj:
            message_obj = message_obj["documentWithCaptionMessage"].get("message", {})

        texto = ""
        
        if "conversation" in message_obj:
            texto = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            texto = message_obj["extendedTextMessage"].get("text", "")
        elif "imageMessage" in message_obj:
            img_obj = message_obj["imageMessage"]
            caption = img_obj.get("caption", "")
            base64_str = img_obj.get("base64") or data.get("base64") or message_obj.get("base64")
            image_url = img_obj.get("url")
            
            if base64_str:
                texto = f"[IMAGE_BASE64:{base64_str}|CAPTION:{caption}]"
            elif message_id:
                texto = f"[IMAGE_ID:{message_id}|CAPTION:{caption}]"
            elif image_url:
                texto = f"[IMAGE_URL:{image_url}|CAPTION:{caption}]"
            else:
                texto = f"[O paciente enviou uma imagem/foto. Legenda: {caption}]" if caption else "[O paciente enviou uma foto/imagem para avaliação]"

        elif "audioMessage" in message_obj:
            audio_obj = message_obj["audioMessage"]
            base64_str = audio_obj.get("base64") or data.get("base64") or message_obj.get("base64")
            audio_url = audio_obj.get("url") or audio_obj.get("directPath")
            if base64_str:
                texto = f"[AUDIO_BASE64:{base64_str}]"
            elif message_id:
                texto = f"[AUDIO_ID:{message_id}]"
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
        if isinstance(message_obj, dict):
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


async def adicionar_ao_buffer(dados: dict):
    """
    Adiciona a mensagem recebida ao buffer de 15 segundos do telefone (se o atendimento da IA não estiver pausado).
    """
    telefone = dados["telefone"]
    push_name = dados["push_name"]
    texto = dados["texto"]
    
    # Checa se a IA está pausada para este número (atendimento humano ativo)
    if agente_esta_pausado(telefone):
        print(f"⏸️ Mensagem de {telefone} ignorada pela IA pois o atendimento humano está ativo (pausa 5 min).")
        return

    # Cancela timer anterior para este número se existir para renovar a janela de 15s
    if telefone in TASKS_ATIVAS:
        task_anterior = TASKS_ATIVAS.pop(telefone)
        if not task_anterior.done():
            task_anterior.cancel()

    if redis_client:
        try:
            key_list = f"whatsapp_agent:buffer:{telefone}"
            key_meta = f"whatsapp_agent:meta:{telefone}"
            
            await redis_client.rpush(key_list, texto)
            await redis_client.expire(key_list, 300)
            if push_name and push_name != "Desconhecido":
                await redis_client.hset(key_meta, "push_name", push_name)
                await redis_client.expire(key_meta, 300)
        except Exception as e:
            print(f"⚠️ Falha no Redis ao adicionar mensagem: {e}. Usando fallback em memória.")
            _adicionar_memoria(telefone, push_name, texto)
    else:
        _adicionar_memoria(telefone, push_name, texto)
        
    task = asyncio.create_task(aguardar_e_processar_buffer(telefone, delay_segundos=15.0))
    TASKS_ATIVAS[telefone] = task


def _adicionar_memoria(telefone: str, push_name: str, texto: str):
    if telefone in BUFFER_MENSAGENS:
        info = BUFFER_MENSAGENS[telefone]
        info["mensagens"].append(texto)
        if push_name and push_name != "Desconhecido":
            info["push_name"] = push_name
    else:
        BUFFER_MENSAGENS[telefone] = {
            "push_name": push_name,
            "mensagens": [texto]
        }


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

    TASKS_ATIVAS.pop(telefone, None)

    push_name = "Desconhecido"
    mensagens_raw: List[str] = []

    if redis_client is not None:
        try:
            key_list = f"whatsapp_agent:buffer:{telefone}"
            key_meta = f"whatsapp_agent:meta:{telefone}"

            raw_mensagens = await redis_client.lrange(key_list, 0, -1)
            mensagens_raw = [
                m.decode("utf-8") if isinstance(m, bytes) else str(m)
                for m in raw_mensagens
            ]

            meta = await redis_client.hgetall(key_meta)
            if meta:
                val = meta.get("push_name") or meta.get(b"push_name")
                if val:
                    push_name = val.decode("utf-8") if isinstance(val, bytes) else str(val)

            await redis_client.delete(key_list, key_meta)
        except Exception as e:
            print(f"⚠️ Erro ao ler buffer no Redis ({e}). Verificando fallback em memória...")
            dados_mem = BUFFER_MENSAGENS.pop(telefone, None)
            if dados_mem:
                mensagens_raw = dados_mem.get("mensagens", [])
                val_mem = dados_mem.get("push_name", "Desconhecido")
                push_name = val_mem.decode("utf-8") if isinstance(val_mem, bytes) else str(val_mem)
    else:
        dados_mem = BUFFER_MENSAGENS.pop(telefone, None)
        if dados_mem:
            mensagens_raw = dados_mem.get("mensagens", [])
            val_mem = dados_mem.get("push_name", "Desconhecido")
            push_name = val_mem.decode("utf-8") if isinstance(val_mem, bytes) else str(val_mem)

    if not mensagens_raw:
        return

    # Processa áudios pendentes (via Base64, ID da Evolution API ou URL)
    mensagens_processadas: List[str] = []
    for msg in mensagens_raw:
        match_b64 = re.search(r'\[AUDIO_BASE64:(.*?)\]', msg, re.DOTALL)
        match_id = re.search(r'\[AUDIO_ID:(.*?)\]', msg, re.DOTALL)
        match_url = re.search(r'\[AUDIO_URL:(.*?)\]', msg, re.DOTALL)

        base64_para_transcrever = None

        if match_b64:
            base64_para_transcrever = match_b64.group(1).strip()
        elif match_id:
            msg_id = match_id.group(1).strip()
            print(f"🎙️ Buscando áudio {msg_id} na Evolution API via findMediaBase64...")
            base64_para_transcrever = await obter_media_base64_evolution(msg_id)

        if base64_para_transcrever:
            print(f"🎙️ Transcrevendo áudio no Whisper...")
            try:
                audio_bytes = decodificar_base64_seguro(base64_para_transcrever)
                
                with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_audio:
                    temp_path = temp_audio.name
                    temp_audio.write(audio_bytes)
                    temp_audio.flush()
                
                if openai_client:
                    with open(temp_path, "rb") as audio_file:
                        transcription = openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )
                        texto_transcrito = transcription.text
                        if texto_transcrito:
                            msg = texto_transcrito
                            print(f"🎙️ Áudio transcrito com sucesso: '{msg}'")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"❌ Erro ao transcrever áudio em Base64: {e}")
                msg = "[Áudio do paciente que não pôde ser transcrito com clareza]"

        elif match_url:
            audio_url = match_url.group(1).strip()
            print(f"🎙️ Baixando áudio com apikey para transcrição no Whisper: {audio_url}")
            headers = {"apikey": EVOLUTION_API_KEY} if EVOLUTION_API_KEY else {}
            try:
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    res = await http_client.get(audio_url, headers=headers)
                    if res.status_code == 200:
                        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_audio:
                            temp_path = temp_audio.name
                            temp_audio.write(res.content)
                        
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

    # Se houver IMAGE_ID nas mensagens, busca o base64 da foto na Evolution API antes de chamar a IA
    if "[IMAGE_ID:" in texto_final:
        pattern_img_id = re.compile(r'\[IMAGE_ID:(.*?)\]', re.DOTALL)
        matches = pattern_img_id.findall(texto_final)
        for match in matches:
            corpo = match.strip()
            caption = ""
            if "|CAPTION:" in corpo:
                msg_id, caption = corpo.split("|CAPTION:", 1)
            else:
                msg_id = corpo
            
            print(f"📸 Buscando foto {msg_id} na Evolution API via findMediaBase64...")
            b64_img = await obter_media_base64_evolution(msg_id)
            if b64_img:
                texto_final = texto_final.replace(f"[IMAGE_ID:{corpo}]", f"[IMAGE_BASE64:{b64_img}|CAPTION:{caption}]")


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
            await adicionar_ao_buffer(dados)
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


@app.api_route("/api/cron/lembretes", methods=["GET", "POST"])
async def trigger_cron_lembretes():
    """
    Endpoint acionado pelo Supabase pg_cron, cron-job.org ou webhook
    para disparar lembretes de consultas 2h antes.
    """
    resultado = await processar_lembretes_2h_antes()
    return resultado


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


