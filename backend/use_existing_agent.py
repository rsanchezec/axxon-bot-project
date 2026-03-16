# ==================================================================================
# SCRIPT: 003_use_existing_agent.py
# DESCRIPCIÓN: Uso de un Agente de Foundry ya existente (axxon-agent) vía Código
# ==================================================================================

import os  # Biblioteca estándar para interactuar con el sistema operativo
from dotenv import load_dotenv  # Biblioteca para cargar variables de entorno desde un archivo .env
from azure.identity import DefaultAzureCredential  # Biblioteca de Azure para autenticación
from azure.ai.projects import AIProjectClient  # Cliente principal para interactuar con Azure AI Projects

# ----------------------------------------------------------------------------------
# 1. CONFIGURACIÓN DEL ENTORNO
# ----------------------------------------------------------------------------------

# Cargar variables de entorno desde el archivo .env ubicado en la raíz del proyecto
load_dotenv()

# Recuperar el endpoint del proyecto desde las variables de entorno
foundry_project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")

# ----------------------------------------------------------------------------------
# 2. INICIALIZACIÓN DEL CLIENTE DEL PROYECTO
# ----------------------------------------------------------------------------------

# Crear el cliente de AI Project usando el endpoint y las credenciales predeterminadas de Azure
project_client = AIProjectClient(
    endpoint=foundry_project_endpoint,
    credential=DefaultAzureCredential(),
)

# ----------------------------------------------------------------------------------
# 3. REFERENCIA AL AGENTE EXISTENTE
# ----------------------------------------------------------------------------------

# Nombre del agente que ya fue creado previamente (en 002_agent_run.py)
agent_name = "axxon-agent"

print(f"Usando el agente existente: {agent_name}")

# ----------------------------------------------------------------------------------
# 4. CONFIGURACIÓN DE LA CONVERSACIÓN
# ----------------------------------------------------------------------------------

# Obtener un cliente compatible con OpenAI desde el cliente del proyecto
openai_client = project_client.get_openai_client()

# Crear un nuevo objeto de conversación para esta sesión
conversation = openai_client.conversations.create()

# Imprimir el ID de la conversación para referencia
print(f"Nueva conversación iniciada con id: {conversation.id}")

# ----------------------------------------------------------------------------------
# 5. BUCLE DE CHAT INTERACTIVO
# ----------------------------------------------------------------------------------

# Bandera para mantener el bucle de chat activo
chat = True

print("\n--- Reanudando comunicación con axxon-agent (escribe 'exit' o 'quit' para salir) ---")

while chat:
    # Obtener la entrada del usuario desde la consola
    user_input = input("Tú: ")
    
    # Verificar si el usuario desea salir del chat
    if user_input.lower() in ["exit", "quit"]:
        chat = False
        print("Saliendo del chat. ¡Adiós!")
    else:
        # Nota: Por defecto, al usar solo el nombre, se llama a la versión más reciente (latest).
        # Si quisieras usar una versión específica, podrías añadir "version": "1" dentro del diccionario 'agent'.
        response = openai_client.responses.create(
            conversation=conversation.id,
            extra_body={
                "agent": {
                    "name": agent_name
                    , "type": "agent_reference"
                    #, "version": "1"  # Descomenta y ajusta si necesitas una versión específica
                }
            },
            input=user_input
        )

        # Imprimir la respuesta del agente manteniendo el personaje
        print(f"axxon-agent: {response.output_text}")
