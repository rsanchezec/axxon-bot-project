#!/bin/bash

# ============================================
# Script de Configuracion Inicial
# Azure Container Apps - AXXON AI Assistant (Texto)
# ============================================
# Este script crea todos los recursos necesarios en Azure
# para deployar el servidor de texto (puerto 8000)
#
# PREREQUISITOS:
#   - Azure CLI instalado (az)
#   - Docker instalado
#   - az login ejecutado
#
# EJECUTAR DESDE: backend/
#   bash text/azure-setup.sh

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Azure Container Apps - Setup Servidor Texto${NC}"
echo -e "${BLUE}================================================${NC}\n"

# ============================================
# CONFIGURACION - EDITA ESTOS VALORES
# ============================================
RESOURCE_GROUP="axxon-container-rg"
LOCATION="eastus"
ACR_NAME="axxonregistrytext"
CONTAINER_APP_NAME="axxon-assistant-text-api"
ENVIRONMENT_NAME="axxon-environment"
IMAGE_NAME="axxon-text-api"

# Pedir confirmacion
echo -e "${YELLOW}Configuracion:${NC}"
echo -e "  Resource Group: ${GREEN}${RESOURCE_GROUP}${NC}"
echo -e "  Location: ${GREEN}${LOCATION}${NC}"
echo -e "  ACR Name: ${GREEN}${ACR_NAME}${NC}"
echo -e "  Container App: ${GREEN}${CONTAINER_APP_NAME}${NC}"
echo -e "  Environment: ${GREEN}${ENVIRONMENT_NAME}${NC}\n"

read -p "Continuar con esta configuracion? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Cancelado${NC}"
    exit 1
fi

# ============================================
# PASO 1: Verificar login
# ============================================
echo -e "\n${YELLOW}Paso 1: Verificando login de Azure...${NC}"
az account show > /dev/null 2>&1 || {
    echo -e "${RED}No estas logueado. Ejecutando: az login${NC}"
    az login
}
SUBSCRIPTION=$(az account show --query name --output tsv)
echo -e "${GREEN}Login verificado - Suscripcion: ${SUBSCRIPTION}${NC}\n"

# ============================================
# PASO 2: Crear Resource Group
# ============================================
echo -e "${YELLOW}Paso 2: Creando Resource Group...${NC}"
az group create \
  --name ${RESOURCE_GROUP} \
  --location ${LOCATION} \
  --output none
echo -e "${GREEN}Resource Group creado: ${RESOURCE_GROUP}${NC}\n"

# ============================================
# PASO 3: Crear Azure Container Registry
# ============================================
echo -e "${YELLOW}Paso 3: Creando Azure Container Registry...${NC}"
az acr create \
  --resource-group ${RESOURCE_GROUP} \
  --name ${ACR_NAME} \
  --sku Basic \
  --admin-enabled true \
  --output none
echo -e "${GREEN}ACR creado: ${ACR_NAME}${NC}\n"

# Obtener credenciales de ACR
echo -e "${YELLOW}Obteniendo credenciales de ACR...${NC}"
ACR_USERNAME=$(az acr credential show --name ${ACR_NAME} --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name ${ACR_NAME} --query "passwords[0].value" --output tsv)
echo -e "${GREEN}Credenciales obtenidas${NC}"
echo -e "${BLUE}  Username: ${ACR_USERNAME}${NC}"
echo -e "${BLUE}  Password: ${ACR_PASSWORD:0:10}...${NC}\n"

# ============================================
# PASO 4: Crear Container App Environment
# ============================================
echo -e "${YELLOW}Paso 4: Creando Container App Environment...${NC}"
az containerapp env create \
  --name ${ENVIRONMENT_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --location ${LOCATION} \
  --output none
echo -e "${GREEN}Environment creado: ${ENVIRONMENT_NAME}${NC}\n"

# ============================================
# PASO 5: Pedir variables de entorno del proyecto
# ============================================
echo -e "${YELLOW}Paso 5: Configuracion de variables de entorno${NC}"
echo -e "${BLUE}Ingresa los valores de tu archivo .env:${NC}\n"

read -p "FOUNDRY_PROJECT_ENDPOINT: " FOUNDRY_ENDPOINT
read -p "MODEL_DEPLOYMENT_NAME [gpt-5.2-chat]: " MODEL_NAME
MODEL_NAME=${MODEL_NAME:-gpt-5.2-chat}
read -p "AI_SEARCH_CONNECTION_NAME: " SEARCH_CONNECTION
read -p "AI_SEARCH_INDEX_NAME: " SEARCH_INDEX
read -p "AZURE_AGENT_NAME [axxon-agent]: " AGENT_NAME
AGENT_NAME=${AGENT_NAME:-axxon-agent}
read -p "Frontend URL (ej: https://tuapp.com): " FRONTEND_URL

echo ""

# ============================================
# PASO 6: Build y push de imagen Docker
# ============================================
echo -e "${YELLOW}Paso 6: Construyendo imagen Docker...${NC}"
# El build context es backend/ y el Dockerfile esta en text/
docker build -f text/Dockerfile -t ${IMAGE_NAME}:latest .
docker tag ${IMAGE_NAME}:latest ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest

echo -e "${YELLOW}Subiendo imagen a ACR...${NC}"
az acr login --name ${ACR_NAME}
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen subida${NC}\n"

# ============================================
# PASO 7: Crear Container App
# ============================================
echo -e "${YELLOW}Paso 7: Creando Container App...${NC}"
az containerapp create \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --environment ${ENVIRONMENT_NAME} \
  --image ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest \
  --registry-server ${ACR_NAME}.azurecr.io \
  --registry-username ${ACR_USERNAME} \
  --registry-password "${ACR_PASSWORD}" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --secrets \
    "foundry-endpoint=${FOUNDRY_ENDPOINT}" \
  --env-vars \
    "FOUNDRY_PROJECT_ENDPOINT=secretref:foundry-endpoint" \
    "MODEL_DEPLOYMENT_NAME=${MODEL_NAME}" \
    "AI_SEARCH_CONNECTION_NAME=${SEARCH_CONNECTION}" \
    "AI_SEARCH_INDEX_NAME=${SEARCH_INDEX}" \
    "AZURE_AGENT_NAME=${AGENT_NAME}" \
    "ENVIRONMENT=production" \
    "ALLOWED_ORIGINS=${FRONTEND_URL}" \
  --output none

echo -e "${GREEN}Container App creado${NC}\n"

# ============================================
# PASO 8: Obtener URL final
# ============================================
echo -e "${YELLOW}Paso 8: Obteniendo URL del servicio...${NC}"
FQDN=$(az containerapp show \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

# Resumen final
echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Setup completado exitosamente!${NC}"
echo -e "${GREEN}================================================${NC}\n"

echo -e "${BLUE}Recursos creados:${NC}"
echo -e "  Resource Group: ${GREEN}${RESOURCE_GROUP}${NC}"
echo -e "  Container Registry: ${GREEN}${ACR_NAME}.azurecr.io${NC}"
echo -e "  Container App: ${GREEN}${CONTAINER_APP_NAME}${NC}"
echo -e "  Environment: ${GREEN}${ENVIRONMENT_NAME}${NC}\n"

echo -e "${BLUE}URLs del servicio:${NC}"
echo -e "  API: ${GREEN}https://${FQDN}${NC}"
echo -e "  WebSocket: ${GREEN}wss://${FQDN}/ws/chat${NC}"
echo -e "  Health: ${GREEN}https://${FQDN}/health${NC}"
echo -e "  Docs: ${GREEN}https://${FQDN}/docs${NC}\n"

echo -e "${BLUE}Credenciales ACR (guardar):${NC}"
echo -e "  Username: ${GREEN}${ACR_USERNAME}${NC}"
echo -e "  Password: ${GREEN}${ACR_PASSWORD}${NC}\n"

echo -e "${YELLOW}Proximos pasos:${NC}"
echo -e "  1. Actualiza tu frontend con la WebSocket URL: ${GREEN}wss://${FQDN}/ws/chat${NC}"
echo -e "  2. Verifica el health check: ${GREEN}https://${FQDN}/health${NC}"
echo -e "  3. Para re-deployar: ${GREEN}bash text/deploy.sh${NC}"
echo -e "  4. Ver logs: ${GREEN}az containerapp logs show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} --follow${NC}\n"
