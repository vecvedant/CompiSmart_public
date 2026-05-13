import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Inter for everything; falls back to system sans. Cabinet Grotesk
        // / Satoshi (the original Vidiom design picks) would need self-hosted
        // woff2 files -- skipping that for the MVP, Inter looks good enough.
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        serif: [
          "Charter",
          "Georgia",
          "Cambria",
          "Times New Roman",
          "serif",
        ],
      },
      keyframes: {
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        blink: "blink 1s step-end infinite",
        shimmer: "shimmer 2s linear infinite",
      },
      backgroundImage: {
        "hero-radial":
          "radial-gradient(circle at 50% -20%, #fff7ed 0%, #ffffff 60%)",
      },
    },
  },
  plugins: [typography],
};
