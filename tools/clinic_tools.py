from typing import List, Any

# Lista Oficial de Ferramentas (Tools) da OpenAI para a Odonto Clínica Londrina
TOOLS: List[Any] = [
    {
        "type": "function",
        "function": {
            "name": "atualizar_cadastro_paciente",
            "description": "Atualiza os dados cadastrais do paciente (nome completo, email, cpf, serviço de interesse) no banco de dados Supabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_real": {"type": "string", "description": "Nome completo do paciente"},
                    "email": {"type": "string", "description": "E-mail do paciente"},
                    "cpf": {"type": "string", "description": "CPF do paciente (mantendo zeros como texto)"},
                    "servico_interesse": {"type": "string", "description": "Serviço que o paciente quer (ex: clareamento, implante, avaliação)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidade",
            "description": "Consulta se uma data e horário estão disponíveis para agendamento no banco de dados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_hora_iso": {"type": "string", "description": "Data e hora ISO (ex: 2026-08-25T14:00:00)"},
                    "profissional": {"type": "string", "description": "Nome do profissional se específico (ex: Dra. Karen, Dra. Karine)"}
                },
                "required": ["data_hora_iso"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_consulta",
            "description": "Grava uma consulta agendada na tabela de agendamentos do Supabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_paciente": {"type": "string", "description": "Nome do paciente"},
                    "servico": {"type": "string", "description": "Serviço agendado"},
                    "profissional": {"type": "string", "description": "Profissional responsável"},
                    "data_hora_iso": {"type": "string", "description": "Data e hora ISO da consulta"}
                },
                "required": ["nome_paciente", "servico", "data_hora_iso"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_ou_reagendar_consulta",
            "description": "Cancela ou remarca uma consulta existente do paciente no Supabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "acao": {"type": "string", "enum": ["cancelar", "reagendar"], "description": "Ação a ser executada"},
                    "nova_data_hora_iso": {"type": "string", "description": "Nova data/hora ISO em caso de reagendamento"},
                    "motivo": {"type": "string", "description": "Motivo do cancelamento ou remarcação se informado"}
                },
                "required": ["acao"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "solicitar_atendimento_humano",
            "description": "Transfere a conversa para um atendente humano real da clínica e pausa as respostas da IA por 5 minutos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string", "description": "Motivo da solicitação de atendimento humano se informado pelo paciente"}
                }
            }
        }
    }
]
