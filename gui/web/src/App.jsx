import { useEffect, useRef, useState } from 'react'

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const wsRef = useRef(null)
  const listRef = useRef(null)

  useEffect(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data)
      if (data.type === 'message') {
        setMessages((prev) => [...prev, { id: data.id, role: data.role, content: data.content }])
      } else if (data.type === 'done') {
        setBusy(false)
      } else if (data.type === 'error') {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'error', content: data.message }])
        setBusy(false)
      }
    }
    return () => ws.close()
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight)
  }, [messages])

  const send = () => {
    const text = input.trim()
    if (!text || !wsRef.current || busy) return
    setMessages((prev) => [...prev, { id: `me-${Date.now()}`, role: 'user', content: text }])
    setInput('')
    setBusy(true)
    wsRef.current.send(JSON.stringify({ type: 'chat', content: text }))
  }

  return (
    <div className="app">
      <header>
        <h1>Tram</h1>
        <span className={`dot ${connected ? 'on' : ''}`} title={connected ? '已连接' : '未连接'} />
      </header>
      <div className="messages" ref={listRef}>
        {messages.length === 0 && <div className="empty">回车对话</div>}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <span className="who">{m.role}</span>
            <div className="content">{m.content}</div>
          </div>
        ))}
        {busy && <div className="msg system"><div className="content">…</div></div>}
      </div>
      <footer>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="输入消息，回车发送"
          disabled={!connected}
        />
        <button onClick={send} disabled={!connected || busy}>发送</button>
      </footer>
    </div>
  )
}
