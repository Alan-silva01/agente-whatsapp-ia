import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client
from evolution import enviar_mensagem_whatsapp

sp_tz = ZoneInfo("America/Sao_Paulo")

def normalizar_data_hora_sp(data_hora_iso: str) -> str:
    """
    Garante que a string ISO possua o sufixo de fuso horário de São Paulo (-03:00)
    caso a IA envie uma data sem timezone explicito.
    """
    if not data_hora_iso:
        return data_hora_iso
    data_hora_str = str(data_hora_iso).strip()
    if len(data_hora_str) >= 10 and not ("+" in data_hora_str or "-" in data_hora_str[10:] or data_hora_str.endswith("Z")):
        data_hora_str += "-03:00"
    return data_hora_str



load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ ATENÇÃO: SUPABASE_URL ou SUPABASE_KEY não configurados no arquivo .env!")

supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def obter_ou_criar_cliente(telefone: str, push_name: str = "Desconhecido") -> Dict[str, Any]:
    """
    Busca o cliente pelo telefone no Supabase.
    Se não existir, cria o cliente com o push_name do WhatsApp.
    """
    if not supabase:
        return {"telefone": telefone, "push_name": push_name, "nome_real": None, "status_jornada": "novo"}
    
    telefone_limpo = str(telefone).split("@")[0].strip()
    
    try:
        # 1. Tenta buscar o cliente existente
        resposta = supabase.table("clientes").select("*").eq("telefone", telefone_limpo).execute()
        
        if resposta.data and isinstance(resposta.data, list) and len(resposta.data) > 0:
            cliente = resposta.data[0]
            if isinstance(cliente, dict):
                if push_name and push_name != "Desconhecido" and cliente.get("push_name") != push_name:
                    try:
                        supabase.table("clientes").update({"push_name": push_name}).eq("telefone", telefone_limpo).execute()
                    except Exception:
                        pass
                    cliente["push_name"] = push_name
                return cliente
        
        # 2. Se não encontrou, insere novo cliente
        novo_cliente: Dict[str, Any] = {
            "telefone": telefone_limpo,
            "push_name": push_name,
            "nome_real": None
        }
        try:
            novo_cliente_full = {**novo_cliente, "status_jornada": "novo"}
            insercao = supabase.table("clientes").insert(novo_cliente_full).execute()
            print(f"✨ Novo cliente cadastrado no Supabase: {telefone_limpo} (pushName: {push_name})")
            if insercao.data and isinstance(insercao.data, list) and len(insercao.data) > 0 and isinstance(insercao.data[0], dict):
                return insercao.data[0]
        except Exception as e:
            # Fallback sem status_jornada se o cache da API do Supabase estiver sendo atualizado
            insercao = supabase.table("clientes").insert(novo_cliente).execute()
            print(f"✨ Novo cliente cadastrado no Supabase (fallback): {telefone_limpo}")
            if insercao.data and isinstance(insercao.data, list) and len(insercao.data) > 0 and isinstance(insercao.data[0], dict):
                return insercao.data[0]

        return novo_cliente
    except Exception as e:
        print(f"⚠️ Erro ao obter/criar cliente no Supabase: {e}")
        return {"telefone": telefone_limpo, "push_name": push_name, "nome_real": None, "status_jornada": "novo"}


def atualizar_dados_paciente(telefone: str, nome_real: Optional[str] = None, email: Optional[str] = None, cpf: Optional[str] = None, servico_interesse: Optional[str] = None) -> bool:
    """
    Atualiza os dados cadastrais do paciente no Supabase (faz merge sem apagar).
    """
    if not supabase:
        return True
    
    dados: Dict[str, Any] = {}
    if nome_real:
        dados["nome_real"] = nome_real
    if email:
        dados["email"] = email
    if cpf:
        dados["cpf"] = cpf
    if servico_interesse:
        dados["servico_interesse"] = servico_interesse
        
    if not dados:
        return True
        
    try:
        supabase.table("clientes").update(dados).eq("telefone", telefone).execute()
        print(f"✅ DADOS DO PACIENTE ATUALIZADOS no Supabase ({telefone}): {dados}")
        return True
    except Exception as e:
        print(f"❌ Erro ao atualizar paciente no Supabase: {e}")
        return False

def consultar_disponibilidade_horario(data_hora_iso: str, profissional: Optional[str] = None) -> Dict[str, Any]:
    """
    Consulta na tabela 'agendamentos' se o horário informado está livre.
    """
    if not supabase:
        return {"disponivel": True, "mensagem": "Horário disponível"}
    
    try:
        data_hora_norm = normalizar_data_hora_sp(data_hora_iso)
        query = supabase.table("agendamentos").select("*").eq("data_hora", data_hora_norm).neq("status", "cancelado")
        if profissional:
            query = query.eq("profissional", profissional)
            
        resposta = query.execute()
        
        if resposta.data and isinstance(resposta.data, list) and len(resposta.data) > 0:
            return {
                "disponivel": False,
                "mensagem": f"O horário {data_hora_iso} já está ocupado. Por favor peça outro horário ao paciente."
            }
        else:
            return {
                "disponivel": True,
                "mensagem": f"O horário {data_hora_iso} está livre para agendamento!"
            }
    except Exception as e:
        print(f"❌ Erro ao consultar disponibilidade no Supabase: {e}")
        return {"disponivel": True, "mensagem": "Disponível"}

def criar_agendamento(telefone: str, nome_paciente: str, servico: str, profissional: Optional[str] = None, data_hora_iso: str = "") -> Dict[str, Any]:
    """
    Insere um novo agendamento na tabela 'agendamentos'.
    """
    if not supabase:
        return {"status": "sucesso", "agendamento_id": "simulado"}
    
    try:
        data_hora_norm = normalizar_data_hora_sp(data_hora_iso)
        novo: Dict[str, Any] = {
            "telefone": telefone,
            "nome_paciente": nome_paciente,
            "servico": servico,
            "profissional": profissional or "Dra. Karen",
            "data_hora": data_hora_norm,
            "status": "agendado"
        }
        res = supabase.table("agendamentos").insert(novo).execute()
        print(f"✅ AGENDAMENTO CRIADO NO SUPABASE: {novo}")
        
        # Atualiza a jornada do cliente automaticamente para pos_agendamento
        atualizar_status_jornada(telefone, "pos_agendamento")

        if res.data and isinstance(res.data, list) and len(res.data) > 0:
            return {"status": "sucesso", "agendamento": res.data[0]}
        return {"status": "sucesso", "agendamento": novo}
    except Exception as e:
        print(f"❌ Erro ao criar agendamento no Supabase: {e}")
        return {"status": "erro", "detalhe": str(e)}

def atualizar_status_jornada(telefone: str, status_jornada: str) -> bool:
    """
    Atualiza a fase da jornada do cliente no Supabase (ex: 'novo', 'pos_agendamento').
    """
    if not supabase or not telefone:
        return True
    try:
        telefone_limpo = str(telefone).split("@")[0].strip()
        supabase.table("clientes").update({"status_jornada": status_jornada}).eq("telefone", telefone_limpo).execute()
        print(f"🔄 Status da jornada do cliente {telefone_limpo} atualizado para '{status_jornada}'")
        return True
    except Exception as e:
        print(f"❌ Erro ao atualizar status_jornada no Supabase: {e}")
        return False

def cancelar_ou_reagendar_agendamento(telefone: str, acao: str, nova_data_hora_iso: Optional[str] = None, motivo: Optional[str] = None) -> Dict[str, Any]:
    """
    Cancela ou reagenda uma consulta existente do paciente.
    """
    if not supabase:
        return {"status": "sucesso"}
    
    try:
        # Busca último agendamento ativo
        res = supabase.table("agendamentos").select("*").eq("telefone", telefone).neq("status", "cancelado").order("created_at", desc=True).limit(1).execute()
        
        if not res.data or not isinstance(res.data, list) or len(res.data) == 0:
            return {"status": "erro", "mensagem": "Nenhum agendamento ativo encontrado para este cliente."}
        
        agendamento = res.data[0]
        if not isinstance(agendamento, dict):
            return {"status": "erro", "mensagem": "Formato de agendamento inválido."}
            
        agendamento_id = agendamento.get("id")
        
        if acao.lower() == "cancelar":
            supabase.table("agendamentos").update({"status": "cancelado"}).eq("id", agendamento_id).execute()
            # Reseta a jornada do cliente para 'novo'
            atualizar_status_jornada(telefone, "novo")
            return {"status": "sucesso", "mensagem": "Agendamento cancelado com sucesso. A jornada do cliente foi resetada para 'novo'."}
        elif acao.lower() == "reagendar" and nova_data_hora_iso:
            supabase.table("agendamentos").update({"status": "reagendado", "data_hora": nova_data_hora_iso}).eq("id", agendamento_id).execute()
            return {"status": "sucesso", "mensagem": f"Agendamento reagendado com sucesso para {nova_data_hora_iso}."}
        
        return {"status": "erro", "mensagem": "Ação inválida ou nova data não informada."}
    except Exception as e:
        print(f"❌ Erro ao alterar agendamento no Supabase: {e}")
        return {"status": "erro", "detalhe": str(e)}

def salvar_mensagem(telefone: str, role: str, content: str):
    """
    Salva uma mensagem (user ou assistant) na tabela de histórico de conversas.
    """
    if not supabase:
        return
    
    try:
        supabase.table("historico_conversas").insert({
            "telefone": telefone,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"❌ Erro ao salvar histórico no Supabase: {e}")

def carregar_historico(telefone: str, limite: int = 10) -> List[Dict[str, str]]:
    """
    Carrega as últimas N mensagens da conversa para alimentar a memória da IA.
    """
    if not supabase:
        return []
    
    try:
        resposta = supabase.table("historico_conversas") \
            .select("role, content, created_at") \
            .eq("telefone", telefone) \
            .order("created_at", desc=True) \
            .limit(limite) \
            .execute()
        
        if not resposta.data or not isinstance(resposta.data, list):
            return []
            
        # Inverte para ficar em ordem cronológica (mais antiga -> mais recente)
        mensagens_raw = list(reversed(resposta.data))
        resultado: List[Dict[str, str]] = []
        for m in mensagens_raw:
            if isinstance(m, dict):
                resultado.append({
                    "role": str(m.get("role", "user")),
                    "content": str(m.get("content", ""))
                })
        return resultado
    except Exception as e:
        print(f"❌ Erro ao carregar histórico: {e}")
        return []

def pausar_agente(telefone: str, minutos: int = 5) -> bool:
    """
    Pausa o atendimento da IA por N minutos para um determinado número no Supabase.
    """
    if not supabase or not telefone:
        return True
        
    try:
        telefone_limpo = str(telefone).split("@")[0].strip()
        # Garante que a linha do cliente existe na tabela clientes antes de atualizar
        obter_ou_criar_cliente(telefone=telefone_limpo)
        
        pausado_ate_sp = (datetime.now(sp_tz) + timedelta(minutes=minutos)).isoformat()
        supabase.table("clientes").update({"pausado_ate": pausado_ate_sp}).eq("telefone", telefone_limpo).execute()
        print(f"⏸️ IA PAUSADA por {minutos} min para {telefone_limpo} (Até {pausado_ate_sp})")
        return True
    except Exception as e:
        print(f"❌ Erro ao pausar agente no Supabase: {e}")
        return False


def agente_esta_pausado(telefone: str) -> bool:
    """
    Verifica se a IA está pausada para o número informado no Supabase (se agora < pausado_ate).
    Suporta tanto strings ISO quanto objetos datetime retornados pelo SDK do Supabase.
    """
    if not supabase or not telefone:
        return False
        
    try:
        telefone_limpo = str(telefone).split("@")[0].strip()
        res = supabase.table("clientes").select("pausado_ate").eq("telefone", telefone_limpo).execute()
        if res.data and isinstance(res.data, list) and len(res.data) > 0:
            cliente = res.data[0]
            if isinstance(cliente, dict):
                pausado_ate_val = cliente.get("pausado_ate")
                if pausado_ate_val and isinstance(pausado_ate_val, str):
                    pausado_ate_dt = datetime.fromisoformat(pausado_ate_val.replace("Z", "+00:00"))
                    if pausado_ate_dt.tzinfo is None:
                        pausado_ate_dt = pausado_ate_dt.replace(tzinfo=timezone.utc)

                    agora_dt = datetime.now(sp_tz)
                    if agora_dt < pausado_ate_dt:
                        restante_seg = int((pausado_ate_dt - agora_dt).total_seconds())
                        print(f"⏸️ Atendimento IA pausado para {telefone_limpo} (restam {restante_seg}s)")
                        return True
        return False
    except Exception as e:
        print(f"⚠️ Erro ao checar status de pausa no Supabase: {e}")
        return False


async def processar_lembretes_2h_antes() -> Dict[str, Any]:
    """
    Busca agendamentos marcados para daqui a 2 horas (janela entre 105 e 150 minutos a partir de agora)
    e dispara a mensagem de lembrete no WhatsApp via Evolution API.
    """
    if not supabase:
        return {"status": "erro", "mensagem": "Supabase não configurado"}

    agora = datetime.now(sp_tz)
    inicio_janela = agora + timedelta(minutes=105)
    fim_janela = agora + timedelta(minutes=150)


    disparados = 0
    erros = 0

    try:
        # Busca agendamentos ativos
        res = supabase.table("agendamentos").select("*").neq("status", "cancelado").execute()
        if not res.data or not isinstance(res.data, list):
            return {"status": "sucesso", "disparados": 0}

        for ag in res.data:
            if not isinstance(ag, dict):
                continue
                
            lembrete_enviado = ag.get("lembrete_enviado", False)
            if lembrete_enviado:
                continue

            data_hora_str = ag.get("data_hora")
            if not data_hora_str:
                continue

            try:
                if isinstance(data_hora_str, str):
                    data_hora_dt = datetime.fromisoformat(data_hora_str.replace("Z", "+00:00"))
                elif isinstance(data_hora_str, datetime):
                    data_hora_dt = data_hora_str
                else:
                    continue

                if data_hora_dt.tzinfo is None:
                    data_hora_dt = data_hora_dt.replace(tzinfo=timezone.utc)

                # Verifica se a consulta está dentro da janela de ~2 horas a partir de agora
                if inicio_janela <= data_hora_dt <= fim_janela:
                    telefone = str(ag.get("telefone") or "")
                    nome_paciente = str(ag.get("nome_paciente") or "Paciente")
                    profissional = str(ag.get("profissional") or "Dra. Karen")
                    data_hora_sp = data_hora_dt.astimezone(sp_tz)
                    horario_formatado = data_hora_sp.strftime("%H:%M")

                    msg_lembrete = f"Oi {nome_paciente}! Passando para lembrar que sua consulta na Odonto Clínica Londrina é hoje às {horario_formatado} com a {profissional}. Você confirma sua presença?"
                    
                    # Dispara via WhatsApp
                    sucesso = await enviar_mensagem_whatsapp(telefone, msg_lembrete)
                    if sucesso:
                        try:
                            supabase.table("agendamentos").update({"lembrete_enviado": True}).eq("id", ag.get("id")).execute()
                        except Exception:
                            pass
                        disparados += 1
                        print(f"🔔 Lembrete 2h enviado com sucesso para {telefone} ({horario_formatado})")
                    else:
                        erros += 1
            except Exception as e_item:
                print(f"⚠️ Erro ao processar item de lembrete: {e_item}")

        return {"status": "sucesso", "disparados": disparados, "erros": erros}
    except Exception as e:
        print(f"❌ Erro ao buscar lembretes no Supabase: {e}")
        return {"status": "erro", "detalhe": str(e)}



