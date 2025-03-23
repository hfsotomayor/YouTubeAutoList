from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
import json

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

def initial_auth():
    """Realiza la autenticación inicial y guarda el token."""
    print("=== Iniciando proceso de autenticación inicial ===")
    
    try:
        if not os.path.exists('YouTubeAutoListClientSecret.json'):
            raise FileNotFoundError(
                "Archivo YouTubeAutoListClientSecret.json no encontrado. " 
                "Descárguelo desde la consola de Google Cloud."
            )

        # Si existe un token previo, lo eliminamos para forzar una nueva autenticación completa
        if os.path.exists('YouTubeAutoListToken.json'):
            print("Eliminando token existente para forzar nueva autenticación...")
            os.remove('YouTubeAutoListToken.json')

        # Configurar el flujo de autenticación para máxima duración
        flow = InstalledAppFlow.from_client_secrets_file(
            'YouTubeAutoListClientSecret.json',
            SCOPES,
            redirect_uri='http://localhost:8080/'
        )
        
        # Forzar acceso offline y prompt de consentimiento con máxima duración
        flow.oauth2session.fetch_token_extra_kwargs = {
            'access_type': 'offline',
            'prompt': 'consent',
            'include_granted_scopes': 'true',
            'approval_prompt': 'force'  # Asegura nuevo refresh_token
        }

        # Ejecutar el servidor local para la autenticación
        credentials = flow.run_local_server(
            port=8080,
            authorization_prompt_message="Por favor, autentícate en el navegador...",
            success_message="Autenticación completada! Puedes cerrar esta ventana."
        )
        
        # Verificar que tenemos refresh_token
        if not credentials.refresh_token:
            raise ValueError(
                "No se pudo obtener el refresh_token. "
                "Asegúrate de haber revocado accesos previos en "
                "https://myaccount.google.com/permissions"
            )
        
        # Preparar datos del token
        token_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        # Guardar token
        with open('YouTubeAutoListToken.json', 'w') as token_file:
            json.dump(token_data, token_file, indent=4)
        
        print("\n=== Autenticación exitosa ===")
        print("Token guardado en 'YouTubeAutoListToken.json'")
        print("\nInformación del token:")
        for key in token_data:
            if key in ['token', 'refresh_token']:
                print(f"{key}: {'*' * 20}")
            else:
                print(f"{key}: {token_data[key]}")
        
        print("\nPasos siguientes:")
        print("1. Copia YouTubeAutoListToken.json al directorio del contenedor")
        print("2. El token debería renovarse automáticamente cuando sea necesario")
        
    except Exception as e:
        print(f"\nError durante la autenticación: {str(e)}")
        raise

if __name__ == "__main__":
    initial_auth()
