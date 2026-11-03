import React from "react"
import {createRoot} from "react-dom/client"
import App from "./App"
import "./styles.css"
import "./premium.css"
import "./operations.css"
import "./platform.css"

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App/></React.StrictMode>
)
