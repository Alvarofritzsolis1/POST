import React from "react"
import {createRoot} from "react-dom/client"
import App from "./App"
import "./styles.css"
import "./premium.css"
import "./operations.css"
import "./platform.css"
import "./v91.css"
import "./ux-2026.css"
import "./v15-premium.css"

// Inicio siempre en la cabecera: los retrocesos internos restauran el scroll explicitamente.
window.scrollTo({top:0,left:0,behavior:"instant"})

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App/></React.StrictMode>
)
