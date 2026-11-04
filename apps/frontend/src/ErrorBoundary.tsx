import {Component, type ReactNode, type ErrorInfo} from "react"

/** Keep navigation alive when a detail page throws during rendering. */
type Props={children:ReactNode;name:string;onClose?:()=>void}
type State={failed:boolean;attempt:number}
export default class ErrorBoundary extends Component<Props,State>{
  state:State={failed:false,attempt:0}
  static getDerivedStateFromError():Partial<State>{return {failed:true}}
  componentDidCatch(error:Error,info:ErrorInfo){
    // Diagnostics only. No contractor names, document content, or user information.
    console.error("[GALANT] Error de renderizado", this.props.name, error.name, error.message, info.componentStack)
  }
  retry=()=>this.setState(s=>({failed:false,attempt:s.attempt+1}))
  render(){
    if(this.state.failed)return <section role="alert" className="ops-recovery">
      <h2>No se pudo mostrar {this.props.name}</h2>
      <p>Ocurrió un error inesperado. Puedes reintentar o volver al listado sin perder los registros guardados.</p>
      <div className="ops-actions"><button type="button" className="primary" onClick={this.retry}>Reintentar</button>
      {this.props.onClose&&<button type="button" className="secondary" onClick={()=>{this.setState({failed:false,attempt:0});this.props.onClose?.()}}>Volver al listado</button>}</div>
    </section>
    return <div key={this.state.attempt}>{this.props.children}</div>
  }
}
