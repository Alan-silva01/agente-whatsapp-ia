# Agente de Atendimento para WhatsApp (Odonto Clínica Londrina)

Projeto de automação de atendimento via WhatsApp utilizando Inteligência Artificial (OpenAI GPT-4o-mini), banco de dados Supabase e integração com a Evolution API.

Este projeto foi desenvolvido como um teste prático de aprendizado para criar um assistente virtual humanizado, capaz de responder mensagens, agendar consultas, entender áudios de voz e manter conversas naturais com pacientes de uma clínica odontológica.

---

## 1. O que este projeto faz

- **Atendimento Humanizado**: A IA atua com o nome de "Bianca", atendente da clínica, com respostas curtas, linguagem natural e sem utilização de emojis.
- **Agrupamento de Mensagens (15 segundos)**: Quando o cliente envia várias mensagens em sequência rápida ou grava áudios seguidos, o sistema aguarda 15 segundos de silêncio para processar todas as mensagens juntas e responder em um único contexto.
- **Transcrição de Áudios de Voz**: Se o paciente enviar uma mensagem de voz no WhatsApp, o sistema baixa o áudio e faz a transcrição em texto utilizando a API Whisper da OpenAI antes de passar para a IA.
- **Simulação de Digitação**: Antes de enviar cada pedaço da resposta, o robô ativa o estado "digitando..." no WhatsApp por um tempo proporcional ao tamanho do texto.
- **Respostas Fracionadas**: Em vez de enviar blocos grandes de texto, as respostas são divididas em frases curtas enviadas uma após a outra.
- **Reconhecimento de Mensagens Citadas**: Se o paciente responder citando ou mencionando uma mensagem específica, o sistema identifica exatamente o conteúdo citado para dar contexto à resposta da IA.
- **Integração com Banco de Dados (Supabase)**: Salva o cadastro do paciente (nome, e-mail, CPF, serviço de interesse), o histórico da conversa e os agendamentos de consultas na agenda da clínica.

---

## 2. Estrutura dos Arquivos do Projeto

Abaixo está a explicação simples do papel de cada arquivo na pasta:

| Arquivo | Função Principal |
| :--- | :--- |
| `main.py` | É o servidor da aplicação (FastAPI). Recebe as notificações (webhooks) da Evolution API quando chegam mensagens no WhatsApp, gerencia o cronômetro de 15 segundos e coordena o fluxo de resposta. |
| `evolution.py` | Responsável por se comunicar com a Evolution API. Envia mensagens de texto, envia o comando "digitando...", e contém a lógica para quebrar mensagens longas em frases curtas. |
| `agent.py` | Contém o cérebro da IA (Bianca). É onde fica o prompt de instruções da atendente, a chamada para a OpenAI (GPT-4o-mini), as regras sem emoji e as ferramentas de agendamento e cadastro. |
| `database.py` | Conecta o projeto ao banco de dados Supabase. Executa comandos para salvar histórico de mensagens, atualizar dados do paciente e consultar horários livres. |
| `schema.sql` | Arquivo de estrutura de dados (SQL). Contém os comandos usados para criar as tabelas no Supabase (`clientes`, `agendamentos`, `historico_conversas`). |
| `.env` | Arquivo de configurações secretas. Armazena as chaves de API da OpenAI, credenciais do Supabase e endereço/token da Evolution API. |
| `.env.example` | Modelo do arquivo `.env` para referência de quais variáveis precisam ser preenchidas. |
| `requirements.txt` | Lista das bibliotecas de Python necessárias para rodar o projeto (FastAPI, Uvicorn, Httpx, OpenAI, Supabase, python-dotenv). |

---

## 3. Como o Fluxo Funciona Passo a Passo

1. **Chegada da Mensagem**: O cliente envia uma mensagem ou áudio no WhatsApp.
2. **Recebimento do Webhook**: A Evolution API envia a notificação HTTP para a rota `/webhook` no `main.py`.
3. **Buffer de 15 Segundos**: O `main.py` coloca a mensagem na lista de espera desse cliente e aguarda 15 segundos. Se novas mensagens chegarem nesse intervalo, o cronômetro zera e recomeça a contar 15 segundos.
4. **Transcrição e Formatação**: Quando os 15 segundos terminam, qualquer áudio do lote é transcrito pelo Whisper. As mensagens são agrupadas em um único texto (incluindo o contexto de citação, se o usuário tiver respondido a uma mensagem específica).
5. **Consulta e Ação da IA**: O `agent.py` envia a conversa para o GPT-4o-mini. Se necessário, a IA chama funções em `database.py` para consultar horários livres ou gravar o agendamento no Supabase.
6. **Simulação e Envio**: A resposta da IA passa pelo filtro de remoção de emojis, é dividida em frases curtas em `evolution.py`, e enviada pedaço por pedaço com o status "digitando..." entre cada frase.

---

## 4. Requisitos de Ambiente

Para rodar este projeto em seu computador local ou servidor, é necessário ter instalado:
- Python 3.10 ou superior.
- Uma conta no Supabase com o banco de dados configurado usando o `schema.sql`.
- Uma chave de API da OpenAI com crédito ativo.
- Uma instância ativa da Evolution API conectada ao seu número de WhatsApp.

---

## 5. Variáveis de Ambiente (.env)

O arquivo `.env` deve conter os seguintes valores:

```env
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-anon-ou-service-role-supabase

OPENAI_API_KEY=sk-sua-chave-openai
OPENAI_MODEL=gpt-4o-mini

EVOLUTION_API_URL=https://sua-instancia-evolution.com
EVOLUTION_API_KEY=sua-chave-evolution
EVOLUTION_INSTANCE=nome-da-instancia
```

---

## 6. Como Executar Localmente

1. Clone ou abra a pasta do projeto no terminal.
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Inicie o servidor FastAPI:
   ```bash
   python main.py
   ```
4. O servidor iniciará no endereço `http://localhost:8001`.

---

## 7. Como Alterar o Comportamento da IA (Prompt)

Para personalizar a atendente (mudança de preços, horários de atendimento, nome da clínica ou tom de conversa), edite o arquivo `agent.py` na variável `system_prompt` (entre as linhas 132 e 185).

Não é necessário reiniciar a aplicação para que as alterações no prompt passem a valer em novos atendimentos.
