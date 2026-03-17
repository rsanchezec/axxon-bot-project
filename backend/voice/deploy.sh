#!/bin/bash

# ============================================
# Script de Re-Deployment
# Azure Container Apps - AXXON AI Assistant (Voz)
# ============================================
# Construye una nueva imagen, la sube a ACR y actualiza el Container App
#
# PREREQUISITOS:
#   - voice/azure-setup.sh ya ejecutado (recursos creados)
#   - Docker instalado
#   - az login ejecutado
#
# EJECUTAR DESDE: backend/
#   bash voice/deploy.sh

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuracion (debe coincidir con azure-setup.sh)
RESOURCE_GROUP="axxon-container-rg"
ACR_NAME="axxonregistrytext"
CONTAINER_APP_NAME="axxon-assistant-voice-api"
IMAGE_NAME="axxon-voice-api"
IMAGE_TAG="v$(date +%Y%m%d-%H%M%S)"

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Azure Container Apps - Deploy Servidor Voz${NC}"
echo -e "${GREEN}================================================${NC}"
echo -e "Image tag: ${IMAGE_TAG}\n"

# Paso 1: Verificar login
echo -e "${YELLOW}Paso 1: Verificando login de Azure...${NC}"
az account show > /dev/null 2>&1 || {
    echo -e "${RED}No estas logueado en Azure. Ejecuta: az login${NC}"
    exit 1
}
echo -e "${GREEN}Login verificado${NC}\n"

# Paso 2: Construir imagen Docker
echo -e "${YELLOW}Paso 2: Construyendo imagen Docker...${NC}"
# El build context es backend/ y el Dockerfile esta en voice/
docker build -f voice/Dockerfile -t ${IMAGE_NAME}:${IMAGE_TAG} .
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen construida${NC}\n"

# Paso 3: Login a ACR y push
echo -e "${YELLOW}Paso 3: Login a Azure Container Registry...${NC}"
az acr login --name ${ACR_NAME}
echo -e "${GREEN}Login a ACR exitoso${NC}\n"

echo -e "${YELLOW}Paso 4: Subiendo imagen a ACR...${NC}"
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest
echo -e "${GREEN}Imagen subida: ${IMAGE_TAG}${NC}\n"

# Paso 5: Actualizar Container App
echo -e "${YELLOW}Paso 5: Actualizando Container App...${NC}"
az containerapp update \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --image ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG} \
  --output none

REVISION=$(az containerapp revision list \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --query "[0].name" -o tsv)
echo -e "${GREEN}Container App actualizado (Revision: ${REVISION})${NC}\n"

# Paso 6: Obtener URL
echo -e "${YELLOW}Paso 6: Obteniendo URL del servicio...${NC}"
FQDN=$(az containerapp show \
  --name ${CONTAINER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Deployment completado!${NC}"
echo -e "${GREEN}================================================${NC}\n"
echo -e "  API:       ${GREEN}https://${FQDN}${NC}"
echo -e "  WebSocket: ${GREEN}wss://${FQDN}/ws/voice${NC}"
echo -e "  Health:    ${GREEN}https://${FQDN}/health${NC}"
echo -e "  Docs:      ${GREEN}https://${FQDN}/docs${NC}"
echo -e "  Tag:       ${GREEN}${IMAGE_TAG}${NC}\n"

# Paso 7: Ver logs (opcional)
read -p "Deseas ver los logs? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${YELLOW}Mostrando logs...${NC}\n"
    az containerapp logs show \
      --name ${CONTAINER_APP_NAME} \
      --resource-group ${RESOURCE_GROUP} \
      --follow
fi
