from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
import json

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']


def clear_oauth_session():
    """Limpia sesiones OAuth previas."""
    try:
        # Eliminar token local
        if os.path.exists('YouTubeAutoListToken.json'):
            os.remove('YouTubeAutoListToken.json')
            print("Token local eliminado.")
        
        print("\nPasos IMPORTANTES antes de continuar:")
        print("1. Abre https://myaccount.google.com/permissions")
        print("2. Busca y revoca acceso a 'YouTubeAutoList'")
        print("3. Borra cookies de Google en tu navegador")
        input("Presiona Enter cuando hayas completado estos pasos...")
    except Exception as e:
        print(f"Error limpiando sesión: {e}")

def initial_auth():
    """Realiza la autenticación inicial y guarda el token."""
    print("=== Iniciando proceso de autenticación inicial ===")
    
    try:
        # Limpiar sesión anterior
        clear_oauth_session()

        # Configuración para forzar nuevo token con los parámetros correctos
        flow = InstalledAppFlow.from_client_secrets_file(
            'YouTubeAutoListClientSecret.json',
            SCOPES
        )

        credentials = flow.run_local_server(
            port=8080,
            authorization_prompt_message="Esperando autenticación...",
            success_message="¡Autorización exitosa!",
            open_browser=True,
            # Parámetros de autorización corregidos
            authorization_prompt_kwargs={
                'access_type': 'offline',
                'prompt': 'consent select_account',
                'include_granted_scopes': 'true'
            }
        )

        # Verificación estricta del refresh_token
        if not credentials.refresh_token:
            raise ValueError(
                "\n¡ERROR! No se obtuvo refresh_token.\n"
                "1. Asegúrate de haber revocado el acceso en https://myaccount.google.com/permissions\n"
                "2. Borra las cookies de Google en tu navegador\n"
                "3. Ejecuta el script nuevamente"
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
