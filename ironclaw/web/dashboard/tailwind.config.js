/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        glass: "rgba(255, 255, 255, 0.05)",
        glassBorder: "rgba(255, 255, 255, 0.1)",
        bgDark: "#0d1117",
        surfaceDark: "#161b22",
        borderDark: "#30363d",
        accent: "#58a6ff",
        accent2: "#3fb950"
      }
    },
  },
  plugins: [],
}
