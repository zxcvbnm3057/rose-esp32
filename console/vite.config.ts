import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    root: '.',
    base: '/console/',
    plugins: [react()],
    server: {
        port: 5173,
        fs: {
            strict: true,
            allow: ['.'],
        },
        proxy: {
            '/api': 'http://127.0.0.1:8000',
            '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
            '/cmd': 'http://127.0.0.1:8000',
        },
    },
})
