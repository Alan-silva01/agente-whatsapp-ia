-- 1. Tabela de Clientes
CREATE TABLE IF NOT EXISTS clientes (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  telefone VARCHAR UNIQUE NOT NULL,
  push_name VARCHAR,
  nome_real VARCHAR,
  email VARCHAR,
  cpf VARCHAR,
  servico_interesse VARCHAR,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Adicionar colunas caso a tabela já exista
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS email VARCHAR;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS cpf VARCHAR;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS servico_interesse VARCHAR;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS pausado_ate TIMESTAMP WITH TIME ZONE;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS status_jornada VARCHAR DEFAULT 'novo';



-- 2. Tabela de Agendamentos (Consultas da Clínica)
CREATE TABLE IF NOT EXISTS agendamentos (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  telefone VARCHAR NOT NULL REFERENCES clientes(telefone) ON DELETE CASCADE,
  nome_paciente VARCHAR,
  servico VARCHAR,
  profissional VARCHAR,
  data_hora TIMESTAMP WITH TIME ZONE NOT NULL,
  status VARCHAR DEFAULT 'agendado', -- 'agendado', 'reagendado', 'cancelado'
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS lembrete_enviado BOOLEAN DEFAULT false;


-- 3. Tabela de Histórico de Mensagens
CREATE TABLE IF NOT EXISTS historico_conversas (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  telefone VARCHAR NOT NULL REFERENCES clientes(telefone) ON DELETE CASCADE,
  role VARCHAR NOT NULL, -- 'user', 'assistant', 'tool'
  content TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Habilitar leitura/escrita para chaves do Supabase
ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE historico_conversas ENABLE ROW LEVEL SECURITY;

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Permitir tudo para a API' AND tablename = 'clientes') THEN
        CREATE POLICY "Permitir tudo para a API" ON clientes FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Permitir tudo para agendamentos' AND tablename = 'agendamentos') THEN
        CREATE POLICY "Permitir tudo para agendamentos" ON agendamentos FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Permitir tudo para historico' AND tablename = 'historico_conversas') THEN
        CREATE POLICY "Permitir tudo para historico" ON historico_conversas FOR ALL USING (true);
    END IF;
END $$;

