import { KeyRound, LockKeyhole } from "lucide-react";
import { useState } from "react";
import { useHistoryAccess } from "../historyAccess";

export function HistoryAccess({ error }: { error?: string }) {
  const { unlock } = useHistoryAccess();
  const [value, setValue] = useState("");
  return (
    <section className="access-panel" aria-label="解锁诊断历史">
      <LockKeyhole size={26} />
      <h2>诊断历史已锁定</h2>
      <p>输入私有演示访问令牌。令牌只保存在当前浏览器会话中。</p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) {
            unlock(value.trim());
            setValue("");
          }
        }}
      >
        <label htmlFor="history-token">访问令牌</label>
        <div className="access-input-row">
          <input
            id="history-token"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            required
          />
          <button className="button-primary" type="submit">
            <KeyRound size={16} /> 解锁
          </button>
        </div>
      </form>
      <small>这不是生产环境用户认证。请仅在可信的私有网络使用。</small>
    </section>
  );
}
