<template>
  <main class="home">
    <section class="hero">
      <p class="eyebrow">Signal Raptor AI Framework</p>
      <h1>Frontend container is running.</h1>
      <p class="summary">
        The Vue and Vite app is available through Docker Compose and ready for feature work.
      </p>
    </section>
  </main>
</template>

<style scoped>
.home {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 2rem;
  background: linear-gradient(135deg, #f4efe6 0%, #d8e7f2 100%);
  color: #16213a;
}

.hero {
  width: min(100%, 42rem);
  padding: 3rem;
  border-radius: 1.5rem;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 1.5rem 4rem rgba(22, 33, 58, 0.12);
  backdrop-filter: blur(8px);
}

.eyebrow {
  margin: 0 0 1rem;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #8a4b2a;
}

h1 {
  margin: 0;
  font-size: clamp(2.2rem, 6vw, 4.25rem);
  line-height: 0.95;
}

.summary {
  margin: 1.5rem 0 0;
  font-size: 1.05rem;
  line-height: 1.6;
}
</style>
