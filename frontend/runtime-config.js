window.SPARX_CONFIG = Object.assign(
  {
    apiBaseUrl: "http://127.0.0.1:8001/api",
    docsUrl: "http://127.0.0.1:8001/docs",
    environmentLabel: "Local Secure",
    requestTimeoutMs: 20000,
    auth: {
      enabled: false,
      required: false,
    },
    firebaseConfig: {
      apiKey: "AIzaSyAgVJno5qP12uSVBYlAxrDUSA0Ot9QGtPU",
      authDomain: "sparxts.firebaseapp.com",
      projectId: "sparxts",
      storageBucket: "sparxts.firebasestorage.app",
      messagingSenderId: "864322979803",
      appId: "1:864322979803:web:a6c6c96f10a38ff5e609fe",
      measurementId: "G-C8LHCRQ842"
    },
  },
  window.SPARX_CONFIG || {},
);
