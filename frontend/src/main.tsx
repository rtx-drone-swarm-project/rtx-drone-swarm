import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import MetricsPage from "./pages/MetricsPage";
import "./styles.css";
import "leaflet/dist/leaflet.css";

const Root = window.location.pathname === "/metrics" ? MetricsPage : App;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
