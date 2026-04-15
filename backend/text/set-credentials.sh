#!/bin/bash

# ============================================
# Configurar credenciales del Service Principal
# Azure Container Apps - AXXON AI Assistant (Texto)
# ============================================
# Ejecutar cuando necesites agregar o actualizar las credenciales
# del Service Principal en el Container App de texto.
#
# EJECUTAR DESDE: backend/
#   bash text/set-credentials.sh

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ============================================
# CREDENCIALES DEL SERVICE PRINCIPAL
# ============================================
AZURE_TENANT_ID="c7800f5e-0a4f-4a7d-bc07-d8cddbc74663"
AZURE_CLIENT_ID="ebbbe29d-c498-426d-a35e-562a175406db"
AZURE_CLIENT_SECRET="9EY8Q~XK5F9Hd8cwefXWw81llP.wowumyCDfYcL~"

# ============================================
# CONFIGURACION DEL CONTAINER APP
# ============================================
RESOURCE_GROUP="axxon-container-rg"
CONTAINER_APP_NAME="axxon-assistant-text-api"

echo -e "${YELLOW}Configurando credenciales en ${CONTAINER_APP_NAME}...${NC}"

az containerapp update \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --set-env-vars \
    "AZURE_TENANT_ID=${AZURE_TENANT_ID}" \
    "AZURE_CLIENT_ID=${AZURE_CLIENT_ID}" \
    "AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}" \
  --output none

echo -e "${GREEN}Credenciales configuradas en ${CONTAINER_APP_NAME}${NC}"
echo -e "${GREEN}El container se reiniciara automaticamente${NC}"
