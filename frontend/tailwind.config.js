/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // dark NLE editor palette
        panel: '#16171c',
        panel2: '#1c1e25',
        panel3: '#23262f',
        edge: '#2c2f3a',
        accent: '#6d6df0',
        bass: '#f0556d',
        mid: '#f0b150',
        high: '#56d2f0',
      },
    },
  },
  plugins: [],
};
