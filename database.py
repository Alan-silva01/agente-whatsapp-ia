import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client


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
        query = supabase.table("agendamentos").select("*").eq("data_hora", data_hora_iso).neq("status", "cancelado")
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
        novo: Dict[str, Any] = {
            "telefone": telefone,
            "nome_paciente": nome_paciente,
            "servico": servico,
            "profissional": profissional or "Dra. Karen",
            "data_hora": data_hora_iso,
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
            return {"status": "sucesso", "mensagem": "Agendamento cancelado com sucesso."}
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
        
        pausado_ate_iso = (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat()
        supabase.table("clientes").update({"pausado_ate": pausado_ate_iso}).eq("telefone", telefone_limpo).execute()
        print(f"⏸️ IA PAUSADA por {minutos} min para {telefone_limpo} (Até {pausado_ate_iso})")
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
                if pausado_ate_val:
                    if isinstance(pausado_ate_val, str):
                        pausado_ate_dt = datetime.fromisoformat(pausado_ate_val.replace("Z", "+00:00"))
                    elif isinstance(pausado_ate_val, datetime):
                        pausado_ate_dt = pausado_ate_val
                    else:
                        return False

                    if pausado_ate_dt.tzinfo is None:
                        pausado_ate_dt = pausado_ate_dt.replace(tzinfo=timezone.utc)

                    agora_dt = datetime.now(timezone.utc)
                    if agora_dt < pausado_ate_dt:
                        restante_seg = int((pausado_ate_dt - agora_dt).total_seconds())
                        print(f"⏸️ Atendimento IA pausado para {telefone_limpo} (restam {restante_seg}s)")
                        return True
        return False
    except Exception as e:
        print(f"⚠️ Erro ao checar status de pausa no Supabase: {e}")
        return False


