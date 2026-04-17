/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#04101f',
        panel: '#091a2d',
        glow: '#6ee7f9',
        ember: '#f59e0b',
      },
      boxShadow: {
        panel: '0 24px 80px rgba(4, 16, 31, 0.45)',
      },
      fontFamily: {
        sans: ['Space Grotesk', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
};