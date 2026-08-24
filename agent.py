import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from openai import OpenAI
from database import (
    atualizar_dados_paciente,
    consultar_disponibilidade_horario,
    criar_agendamento,
    cancelar_ou_reagendar_agendamento,
    salvar_mensagem,
    carregar_historico,
    pausar_agente
)
from prompts.bianca_prompt import obter_system_prompt_bianca
from tools.clinic_tools import TOOLS

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def remover_emojis(texto: str) -> str:
    """Garante que nenhum emoji passe nas respostas da Bianca."""
    if not texto:
        return ""
    import re
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # símbolos & pictogramas
        "\U0001F680-\U0001F6FF"  # transporte & mapa
        "\U0001F1E0-\U0001F1FF"  # bandeiras
        "\U00002700-\U000027BF"  # dingbats
        "\U0001F900-\U0001F9FF"  # suplementos
        "\U00002600-\U000026FF"  # símbolos variados
        "]+", flags=re.UNICODE
    )
    return emoji_pattern.sub('', texto)


def remover_base64_para_banco(texto: str) -> str:
    """
    Substitui strings de imagem em Base64/URL por descrições amigáveis no histórico do Supabase.
    """
    if not texto:
        return ""
    import re

    def sub_img(match):
        corpo = match.group(1)
        caption = ""
        if "|CAPTION:" in corpo:
            _, caption = corpo.split("|CAPTION:", 1)
        caption = caption.strip()
        return f"[Foto enviada pelo paciente. Legenda: {caption}]" if caption else "[Foto enviada pelo paciente]"

    texto = re.sub(r'\[IMAGE_BASE64:(.*?)\]', sub_img, texto, flags=re.DOTALL)
    texto = re.sub(r'\[IMAGE_URL:(.*?)\]', sub_img, texto, flags=re.DOTALL)
    return texto.strip()


def formatar_conteudo_multimodal(texto: str) -> Any:
    """
    Formata mensagens com imagem para o padrão de Visão Computacional (Multimodal) da OpenAI.
    Utiliza regex com re.DOTALL para extrair Base64/URL sem quebrar com quebras de linha.
    """
    if not texto or ("[IMAGE_BASE64:" not in texto and "[IMAGE_URL:" not in texto):
        return texto

    import re
    partes_conteudo: List[Dict[str, Any]] = []

    # 1. Procura por IMAGE_BASE64
    pattern_b64 = re.compile(r'\[IMAGE_BASE64:(.*?)\]', re.DOTALL)
    matches_b64 = pattern_b64.findall(texto)

    for match in matches_b64:
        corpo = match.strip()
        caption = ""
        if "|CAPTION:" in corpo:
            base64_data, caption = corpo.split("|CAPTION:", 1)
        else:
            base64_data = corpo

        # Limpa quebras de linha/espaços da string base64
        base64_clean = re.sub(r'\s+', '', base64_data)
        if base64_clean:
            url_formatada = base64_clean if base64_clean.startswith("data:") else f"data:image/jpeg;base64,{base64_clean}"
            partes_conteudo.append({
                "type": "image_url",
                "image_url": {"url": url_formatada}
            })

    # 2. Procura por IMAGE_URL
    pattern_url = re.compile(r'\[IMAGE_URL:(.*?)\]', re.DOTALL)
    matches_url = pattern_url.findall(texto)

    for match in matches_url:
        corpo = match.strip()
        caption = ""
        if "|CAPTION:" in corpo:
            img_url, caption = corpo.split("|CAPTION:", 1)
        else:
            img_url = corpo

        img_url_clean = img_url.strip()
        if img_url_clean:
            partes_conteudo.append({
                "type": "image_url",
                "image_url": {"url": img_url_clean}
            })

    # 3. Limpa o texto (substitui as tags das imagens por texto amigável)
    texto_limpo = remover_base64_para_banco(texto)
    if not texto_limpo:
        texto_limpo = "O paciente enviou uma foto para você visualizar."

    partes_conteudo.insert(0, {"type": "text", "text": texto_limpo})
    return partes_conteudo


async def processar_mensagem_agente(cliente: Dict[str, Any], texto_usuario: str) -> str:
    """
    Processa a mensagem com o prompt oficial da Bianca (Odonto Clínica Londrina) + Supabase Tools + Visão GPT-4o-mini.
    """
    telefone = str(cliente.get("telefone", ""))
    push_name = str(cliente.get("push_name", "Desconhecido"))
    nome_real = cliente.get("nome_real")
    email = cliente.get("email")
    cpf = cliente.get("cpf")
    servico_interesse = cliente.get("servico_interesse")

    if not client:
        return "OPENAI_API_KEY não configurada no arquivo .env!"

    # Salva mensagem tratada no Supabase (sem a base64 gigante)
    texto_limpo_banco = remover_base64_para_banco(texto_usuario)
    salvar_mensagem(telefone, "user", texto_limpo_banco)
    historico = carregar_historico(telefone, limite=12)

    agora_iso = datetime.now().isoformat()
    dados_cliente_str = f"Nome: {nome_real or 'SEM CADASTRO'}, Email: {email or 'SEM EMAIL'}, CPF: {cpf or 'SEM CPF'}, Serviço: {servico_interesse or 'Nenhum'}" if (nome_real or email or cpf) else "SEM CADASTRO"

    # Carrega prompt limpo do módulo prompts
    system_prompt = obter_system_prompt_bianca(agora_iso, telefone, dados_cliente_str)

    messages: List[Any] = [{"role": "system", "content": system_prompt}]
    for msg in historico:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Se a mensagem atual do usuário contiver marcadores de imagem, injeta no último item (user)
    if "[IMAGE_BASE64:" in texto_usuario or "[IMAGE_URL:" in texto_usuario:
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = formatar_conteudo_multimodal(texto_usuario)

    print(f"🧠 Enviando prompt da Bianca para GPT-4o-mini ({telefone})...")
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )

        resposta_mensagem = response.choices[0].message

        # Trata execução de chamadas de ferramentas (Tools)
        if resposta_mensagem.tool_calls:
            messages.append(resposta_mensagem.model_dump())
            
            for tool_call in resposta_mensagem.tool_calls:
                fn_obj = getattr(tool_call, "function", None)
                fn_name = getattr(fn_obj, "name", "") if fn_obj else ""
                args_str = getattr(fn_obj, "arguments", "{}") if fn_obj else "{}"
                args = json.loads(args_str or "{}")
                print(f"🛠️ Tool chamada: {fn_name} com args {args}")

                resultado: Dict[str, Any] = {}
                if fn_name == "atualizar_cadastro_paciente":
                    sucesso = atualizar_dados_paciente(
                        telefone=telefone,
                        nome_real=args.get("nome_real"),
                        email=args.get("email"),
                        cpf=args.get("cpf"),
                        servico_interesse=args.get("servico_interesse")
                    )
                    resultado = {"status": "sucesso" if sucesso else "erro"}
                
                elif fn_name == "consultar_disponibilidade":
                    resultado = consultar_disponibilidade_horario(
                        data_hora_iso=args.get("data_hora_iso", ""),
                        profissional=args.get("profissional")
                    )
                
                elif fn_name == "agendar_consulta":
                    resultado = criar_agendamento(
                        telefone=telefone,
                        nome_paciente=args.get("nome_paciente", nome_real or push_name),
                        servico=args.get("servico", servico_interesse or "Consulta"),
                        profissional=args.get("profissional", "Dra. Karen"),
                        data_hora_iso=args.get("data_hora_iso", "")
                    )
                
                elif fn_name == "cancelar_ou_reagendar_consulta":
                    resultado = cancelar_ou_reagendar_agendamento(
                        telefone=telefone,
                        acao=args.get("acao", ""),
                        nova_data_hora_iso=args.get("nova_data_hora_iso"),
                        motivo=args.get("motivo")
                    )

                elif fn_name == "solicitar_atendimento_humano":
                    pausar_agente(telefone, minutos=5)
                    resultado = {
                        "status": "sucesso",
                        "mensagem": "Atendimento transferido para humano e a IA foi pausada por 5 minutos."
                    }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(resultado)
                })

            # Segunda chamada para a OpenAI produzir o texto amigável final
            response_final = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages
            )
            texto_final = response_final.choices[0].message.content or ""
            texto_final_sem_emoji = remover_emojis(texto_final)
            salvar_mensagem(telefone, "assistant", texto_final_sem_emoji)
            return texto_final_sem_emoji

        texto_final = resposta_mensagem.content or ""
        texto_final_sem_emoji = remover_emojis(texto_final)
        salvar_mensagem(telefone, "assistant", texto_final_sem_emoji)
        return texto_final_sem_emoji

    except Exception as e:
        print(f"❌ Erro na OpenAI API: {e}")
        return "Tive um probleminha técnico por um momento. Pode repetir por favor?"

