# LeviLibrary - Demo

## Descrizione
LeviLibrary è un sito web di gestione di libri con autenticazione tramite email dell'organizzazione. Solo gli utenti con email dell'organizzazione (configurata con `ALLOWED_DOMAIN`) possono accedere, a meno che la propria email non sia inserita nella lista degli admin.

## Requisiti
- Python 3.10+
- Uvicorn
- FastAPI
- SQLAlchemy (o altro ORM utilizzato nel backend)

## Configurazione

1. Configurare le variabili d'ambiente (consigliato in produzione/Azure) oppure creare un file `secrets.json` (legacy).

### Variabili d'ambiente

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` (opzionale; default: `https://<host>/auth/callback`)
- `ADMIN_EMAILS` (opzionale; email separate da virgola)
- `ALLOWED_DOMAIN` (opzionale; default: `levi.edu.it`)

### secrets.json (legacy)

Creare un file `secrets.json` nella root del progetto con le credenziali seguenti:

```json
{
  "CLIENT_ID": "",
  "CLIENT_SECRET": "",
  "REDIRECT_URI": "https://<host>/auth/callback",
  "admin_emails": [
    ""
  ]
}
```

- `CLIENT_ID` e `CLIENT_SECRET` servono per l’autenticazione OAuth.  
- `REDIRECT_URI` deve corrispondere all'URL reale di callback (es: `https://<host>/auth/callback`).  
- `admin_emails` è una lista di email che possono accedere anche se non appartengono al dominio configurato.  

## Avvio del sito

1. Aprire un terminale nella cartella del progetto.  
2. Eseguire:

```bash
uvicorn backend:app --reload
```

3. Il sito sarà accessibile su:

```
http://127.0.0.1:8000

(In produzione usa il tuo dominio reale.)
```

## Accesso

- Gli utenti devono utilizzare un’email dell’organizzazione (dominio configurato con `ALLOWED_DOMAIN`) per autenticarsi.  
- Se la tua email non appartiene al dominio, puoi inserirla nella lista `admin_emails` di `secrets.json` per ottenere l’accesso.  

## Funzionalità principali

- Visualizzazione della libreria con paginazione  
- Ricerca libri per ID, titolo o autore  
- Aggiunta/rimozione di libri attraverso il pannello admin
- Autenticazione tramite email dell’organizzazione con Google OAuth
