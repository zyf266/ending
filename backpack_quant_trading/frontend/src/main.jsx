import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './assets/variables.css'
import './assets/theme.css'
import './App.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('app')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)

