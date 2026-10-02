import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles/tokens.css'
import './styles/base.css'
import './styles/shell.css'
import './styles/board.css'
import './styles/lens.css'
import './styles/today.css'
import './styles/case.css'
import './styles/npl.css'
import './styles/import.css'
import './styles/screens.css'
import { PrefsProvider } from './lib/prefs.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { AuthGate } from './components/AuthGate.jsx'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <PrefsProvider>
      <ToastProvider>
        <BrowserRouter>
          <AuthGate>
            <App />
          </AuthGate>
        </BrowserRouter>
      </ToastProvider>
    </PrefsProvider>
  </StrictMode>,
)
