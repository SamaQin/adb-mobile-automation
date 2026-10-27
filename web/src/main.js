import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './styles.css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

createApp(App).use(createPinia()).mount('#app')
