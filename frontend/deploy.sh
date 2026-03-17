#!/bin/bash

# ============================================
# Script de Re-Deployment
# Azure Container Apps - AXXON AI Assistant (Frontend)
# ============================================
# Reconstruye la imagen con las URLs actuales y actualiza el Container App
#
# PREREQUISITOS:
#   - azure-setup.sh ya ejecutado (recursos creados)
#   - Docker instalado
#   - az login ejecutado
#
# EJECUTAR DESDE: frontend/
#   bash deploy.sh

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuracion (debe coincidir con azure-setup.sh)
RESOURCE_GROUP="axxon-container-rg"
ACR_NAME="axxonregistrytext"
CONTAINER_APP_NAME="axxon-assistant-frontend"
IMAGE_NAME="axxon-frontend"
IMAGE_TAG="v$(date +%Y%m%d-%H%M%S)"

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Azure Container Apps - Deploy Frontend${NC}"
echo -e "${GREEN}================================================${NC}"
echo -e "Image tag: ${IMAGE_TAG}\n"

# Paso 1: Verificar login
echo -e "${YELLOW}Paso 1: Verificando login de Azure...${NC}"
az account show > /dev/null 2>&1 || {
    echo -e "${RED}No estas logueado en Azure. Ejecuta: az login${NC}"
    exit 1
}
echo -e "${GREEN}Login verificado${NC}\n"

# Paso 2: Obtener URLs de los backends automaticamente
echo -e "${YELLOW}Paso 2: Obteniendo URLs de los backends...${NC}"

TEXT_FQDN=$(az containerapp show \
  --name axxon-assistant-text-api \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv 2>/dev/null) || true

VOICE_FQDN=$(az containerapp show \
  --name axxon-assistant-voice-api \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv 2>/dev/null) || true

if [ -z "$TEXT_FQDN" ] || [ -z "$VOICE_FQDN" ]; then
    echo -e "${YELLOW}No se pudieron obtener las URLs automaticamente.${NC}"
    echo -e "${YELLOW}Ingresalas manualmente:${NC}\n"
    read -p "URL WebSocket texto (wss://...): " TEXT_WS_URL
    read -p "URL WebSocket voz   (wss://...): " VOICE_WS_URL
else
    TEXT_WS_URL="wss://${TEXT_FQDN}/ws/chat"
    VOICE_WS_URL="wss://${VOICE_FQDN}/ws/voice"
    echo -e "${GREEN}  Texto: ${TEXT_WS_URL}${NC}"
    echo -e "${GREEN}  Voz:   ${VOICE_WS_URL}${NC}\n"
fi

# Paso 3: Construir imagen Docker
echo -e "${YELLOW}Paso 3: Construyendo imagen Docker...${NC}"
docker build \
  --build-arg VITE_TEXT_WS_URL="${TEXT_WS_URL}" \
  --build-arg VITE_VOICE_WS_URL="${VOICE_WS_URL}" \
  -t ${IMAGE_NAME}:${IMAGE_TAG} .
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen construida${NC}\n"

# Paso 4: Login a ACR y push
echo -e "${YELLOW}Paso 4: Login a Azure Container Registry...${NC}"
az acr login --name ${ACR_NAME}
echo -e "${GREEN}Login a ACR exitoso${NC}\n"

echo -e "${YELLOW}Paso 5: Subiendo imagen a ACR...${NC}"
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen subida: ${IMAGE_TAG}${NC}\n"

# Paso 6: Actualizar Container App
echo -e "${YELLOW}Paso 6: Actualizando Container App...${NC}"
az containerapp update \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --image ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG} \
  --output none
echo -e "${GREEN}Container App actualizado${NC}\n"

# Paso 7: Obtener URL
FQDN=$(az containerapp show \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Deployment completado!${NC}"
echo -e "${GREEN}================================================${NC}\n"
echo -e "  Frontend: ${GREEN}https://${FQDN}${NC}"
echo -e "  Health:   ${GREEN}https://${FQDN}/health${NC}"
echo -e "  Tag:      ${GREEN}${IMAGE_TAG}${NC}\n"
