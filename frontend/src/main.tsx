import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { followTheme } from './themeRoot.ts'

// index.html chose the theme before the first paint; from here on it follows
// the system and the reader's choice.
followTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
