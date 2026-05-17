#!/bin/bash
# Script para rodar localmente

echo "🚀 PUMPS - Iniciando..."

# Criar venv se não existir
if [ ! -d "venv" ]; then
    echo "📦 Criando ambiente virtual..."
    python3 -m venv venv
fi

# Ativar venv
echo "✅ Ativando ambiente virtual..."
source venv/bin/activate

# Instalar dependências
echo "📥 Instalando dependências..."
pip install -r requirements.txt

# Verificar .env
if [ ! -f ".env" ]; then
    echo "⚠️ Arquivo .env não encontrado!"
    echo "📝 Criando .env de .env.example..."
    cp .env.example .env
    echo "✏️ Edite .env com suas credenciais e execute novamente"
    exit 1
fi

# Rodar
echo "🎯 Iniciando PUMPS..."
python app.py
