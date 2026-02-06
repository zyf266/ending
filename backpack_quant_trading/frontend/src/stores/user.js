import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe } from '../api/auth'

export const useUserStore = defineStore('user', () => {
  const user = ref(null)
  const token = ref(localStorage.getItem('token'))

  const isLoggedIn = computed(() => !!token.value)

  async function fetchUser() {
    if (!token.value) return
    try {
      const res = await getMe()
      user.value = res
      return res
    } catch {
      token.value = null
      user.value = null
    }
  }

  function setAuth(tok, u) {
    token.value = tok
    user.value = u
    if (tok) localStorage.setItem('token', tok)
    else localStorage.removeItem('token')
    if (u) localStorage.setItem('user', JSON.stringify(u))
    else localStorage.removeItem('user')
  }

  function logout() {
    setAuth(null, null)
  }

  return { user, token, isLoggedIn, fetchUser, setAuth, logout }
})
