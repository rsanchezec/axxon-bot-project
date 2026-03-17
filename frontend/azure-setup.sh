#!/bin/bash

# ============================================
# Script de Configuracion Inicial
# Azure Container Apps - AXXON AI Assistant (Frontend)
# ============================================
# Este script crea el Container App para el frontend React
#
# PREREQUISITOS:
#   - Azure CLI instalado (az)
#   - Docker instalado
#   - az login ejecutado
#   - Los backends ya deployados (para obtener sus URLs)
#
# EJECUTAR DESDE: frontend/
#   bash azure-setup.sh

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Azure Container Apps - Setup Frontend${NC}"
echo -e "${BLUE}================================================${NC}\n"

# ============================================
# CONFIGURACION - EDITA ESTOS VALORES
# ============================================
RESOURCE_GROUP="axxon-container-rg"
LOCATION="eastus"
ACR_NAME="axxonregistrytext"
CONTAINER_APP_NAME="axxon-assistant-frontend"
ENVIRONMENT_NAME="axxon-environment"
IMAGE_NAME="axxon-frontend"

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
# PASO 2: Verificar que RG, ACR y Environment existen
# ============================================
echo -e "${YELLOW}Paso 2: Verificando recursos existentes...${NC}"

az group show --name ${RESOURCE_GROUP} > /dev/null 2>&1 || {
    echo -e "${RED}Resource Group '${RESOURCE_GROUP}' no existe. Ejecuta primero text/azure-setup.sh o voice/azure-setup.sh${NC}"
    exit 1
}
echo -e "${GREEN}  Resource Group: OK${NC}"

az acr show --resource-group ${RESOURCE_GROUP} --name ${ACR_NAME} > /dev/null 2>&1 || {
    echo -e "${RED}ACR '${ACR_NAME}' no existe. Ejecuta primero text/azure-setup.sh o voice/azure-setup.sh${NC}"
    exit 1
}
echo -e "${GREEN}  ACR: OK${NC}"

az containerapp env show --name ${ENVIRONMENT_NAME} --resource-group ${RESOURCE_GROUP} > /dev/null 2>&1 || {
    echo -e "${RED}Environment '${ENVIRONMENT_NAME}' no existe. Ejecuta primero text/azure-setup.sh o voice/azure-setup.sh${NC}"
    exit 1
}
echo -e "${GREEN}  Environment: OK${NC}\n"

# Obtener credenciales de ACR
ACR_USERNAME=$(az acr credential show --name ${ACR_NAME} --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name ${ACR_NAME} --query "passwords[0].value" --output tsv)

# ============================================
# PASO 3: Pedir URLs de los backends
# ============================================
echo -e "${YELLOW}Paso 3: URLs de los backends deployados${NC}"
echo -e "${BLUE}Ingresa las URLs de los Container Apps de texto y voz:${NC}\n"

read -p "URL WebSocket texto (ej: wss://axxon-assistant-text-api.azurecontainerapps.io/ws/chat): " TEXT_WS_URL
read -p "URL WebSocket voz   (ej: wss://axxon-assistant-voice-api.azurecontainerapps.io/ws/voice): " VOICE_WS_URL

echo ""

# ============================================
# PASO 4: Build de imagen Docker
# ============================================
echo -e "${YELLOW}Paso 4: Construyendo imagen Docker...${NC}"
# Las variables VITE_ se inyectan en build time (Vite las embebe en el JS)
docker build \
  --build-arg VITE_TEXT_WS_URL="${TEXT_WS_URL}" \
  --build-arg VITE_VOICE_WS_URL="${VOICE_WS_URL}" \
  -t ${IMAGE_NAME}:latest .

docker tag ${IMAGE_NAME}:latest ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest

echo -e "${YELLOW}Subiendo imagen a ACR...${NC}"
az acr login --name ${ACR_NAME}
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen subida${NC}\n"

# ============================================
# PASO 5: Crear Container App
# ============================================
echo -e "${YELLOW}Paso 5: Creando Container App...${NC}"
az containerapp create \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --environment ${ENVIRONMENT_NAME} \
  --image ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest \
  --registry-server ${ACR_NAME}.azurecr.io \
  --registry-username ${ACR_USERNAME} \
  --registry-password "${ACR_PASSWORD}" \
  --target-port 80 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.25 \
  --memory 0.5Gi \
  --output none

echo -e "${GREEN}Container App creado${NC}\n"

# ============================================
# PASO 6: Obtener URL final
# ============================================
echo -e "${YELLOW}Paso 6: Obteniendo URL del frontend...${NC}"
FQDN=$(az containerapp show \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

# Resumen final
echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Setup completado exitosamente!${NC}"
echo -e "${GREEN}================================================${NC}\n"

echo -e "${BLUE}Frontend:${NC}"
echo -e "  URL: ${GREEN}https://${FQDN}${NC}"
echo -e "  Health: ${GREEN}https://${FQDN}/health${NC}\n"

echo -e "${BLUE}Backends configurados:${NC}"
echo -e "  Texto: ${GREEN}${TEXT_WS_URL}${NC}"
echo -e "  Voz:   ${GREEN}${VOICE_WS_URL}${NC}\n"

echo -e "${YELLOW}IMPORTANTE: Actualiza ALLOWED_ORIGINS en los backends${NC}"
echo -e "  Agrega ${GREEN}https://${FQDN}${NC} a los Container Apps de texto y voz:"
echo -e "  ${BLUE}az containerapp update --name axxon-assistant-text-api --resource-group ${RESOURCE_GROUP} --set-env-vars \"ALLOWED_ORIGINS=https://${FQDN}\"${NC}"
echo -e "  ${BLUE}az containerapp update --name axxon-assistant-voice-api --resource-group ${RESOURCE_GROUP} --set-env-vars \"ALLOWED_ORIGINS=https://${FQDN}\"${NC}\n"

echo -e "${YELLOW}Proximos pasos:${NC}"
echo -e "  1. Actualiza ALLOWED_ORIGINS en los backends (comandos de arriba)"
echo -e "  2. Abre ${GREEN}https://${FQDN}${NC} en el navegador"
echo -e "  3. Para re-deployar: ${GREEN}bash deploy.sh${NC}\n"
