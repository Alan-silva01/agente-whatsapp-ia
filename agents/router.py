import json
from typing import Dict, Any, Optional
from openai import OpenAI
from prompts.router_prompt import obter_system_prompt_router

def classificar_agente_destinatario(client: OpenAI, model: str, cliente: Dict[str, Any], texto_usuario: str, agora_iso: str) -> str:
    """
    Roteador Inteligente: analisa o estado do cliente e o texto para determinar qual o Agente Especialista ideal.
    Retorna uma das opções: "POS_AGENDAMENTO", "FINANCEIRO", "DUVIDAS", "AGENDAMENTO", "SUPORTE".
    """
    telefone = str(cliente.get("telefone", ""))
    status_jornada = str(cliente.get("status_jornada", "novo"))
    nome_real = cliente.get("nome_real")
    email = cliente.get("email")
    cpf = cliente.get("cpf")
    servico_interesse = cliente.get("servico_interesse")
    
    dados_cliente_str = f"Nome: {nome_real or 'SEM CADASTRO'}, Email: {email or 'SEM EMAIL'}, CPF: {cpf or 'SEM CPF'}, Serviço: {servico_interesse or 'Nenhum'}"

    # Atalho rápido: se o cliente já está em Pós-Agendamento e fala de assuntos da consulta
    texto_lc = (texto_usuario or "").lower()
    palavras_pos = ["consulta", "horário", "horario", "cancelar", "reagendar", "mudar", "remarcar", "documento", "atrasar", "chegar"]
    if status_jornada == "pos_agendamento" and any(p in texto_lc for p in palavras_pos):
        print(f"🔀 Roteador: Cliente em pós-agendamento detectado -> Roteando para POS_AGENDAMENTO")
        return "POS_AGENDAMENTO"

    prompt = obter_system_prompt_router(agora_iso, telefone, status_jornada, dados_cliente_str)

    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": texto_usuario}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        conteudo = res.choices[0].message.content or "{}"
        dados = json.loads(conteudo)
        agente_escolhido = str(dados.get("agente", "AGENDAMENTO")).upper().strip()

        agentes_validos = ["POS_AGENDAMENTO", "FINANCEIRO", "DUVIDAS", "AGENDAMENTO", "SUPORTE"]
        if agente_escolhido in agentes_validos:
            print(f"🔀 Roteador OpenAI: Roteado para o Agente '{agente_escolhido}'")
            return agente_escolhido

        print(f"🔀 Roteador: Opção '{agente_escolhido}' inválida. Fallback -> AGENDAMENTO")
        return "AGENDAMENTO"
    except Exception as e:
        print(f"⚠️ Erro ao rotear agente via OpenAI ({e}). Fallback -> AGENDAMENTO")
        return "AGENDAMENTO"
