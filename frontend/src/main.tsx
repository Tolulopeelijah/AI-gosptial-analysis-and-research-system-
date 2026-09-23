import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Leaflet's stylesheet is imported before the app stylesheet so the application
// token layer can override Leaflet's default chrome.
import 'leaflet/dist/leaflet.css'
import './index.css'

import { App } from './App'

const container = document.getElementById('root')
if (!container) {
  throw new Error('Root container #root was not found in index.html')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
