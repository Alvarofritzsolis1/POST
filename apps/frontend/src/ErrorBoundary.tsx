import {Component, type ErrorInfo, type ReactNode} from "react"

type Props = {
  children:ReactNode
  label?:string
  onClose?:()=>void
  resetKey?:string
}
type State = {failed:boolean}

/** Aísla fallos de un panel: el menú general nunca debe quedar en blanco. */
export default class ErrorBoundary extends Component<Props,State> {
  state:State = {failed:false}
  static getDerivedStateFromError():State {return {failed:true}}
  componentDidCatch(error:Error,info:ErrorInfo) {
    // Diagnóstico local sin enviar RUT, documentos ni estado de cuenta.
    console.error("[GALANT] Error de renderizado en el panel",error.message,info.componentStack)
  }
  componentDidUpdate(prev:Props) {
    if(this.state.failed && prev.resetKey!==this.props.resetKey) {
      this.setState({failed:false})
    }
  }
  render() {
    if(!this.state.failed)return this.props.children
    return <section role="alert" className="galant-error-boundary">
      <h3>No pudimos abrir {this.props.label||"esta sección"}</h3>
      <p>El resto de GALANT sigue disponible. Puedes volver al listado o reintentar.</p>
      <div className="galant-error-actions">
        {this.props.onClose&&<button type="button" className="secondary" onClick={()=>{this.setState({failed:false});this.props.onClose?.()}}>Volver al listado</button>}
        <button type="button" className="primary" onClick={()=>this.setState({failed:false})}>Reintentar</button>
      </div>
    </section>
  }
}
