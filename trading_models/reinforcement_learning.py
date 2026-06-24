"""
====================================================================
 نماذج التعلم المعزز لأنظمة التداول الآلي
 Reinforcement Learning Models for Automated Trading
====================================================================
النماذج المشمولة:
  1. بيئة التداول المخصصة (Custom Trading Environment)
  2. DQN (Deep Q-Network) + Double DQN + Dueling DQN
  3. PPO (Proximal Policy Optimization)
  4. A2C (Advantage Actor-Critic)
  5. SAC (Soft Actor-Critic) للتداول المستمر
  6. Rainbow DQN
  7. Multi-Asset Portfolio Environment
====================================================================
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from collections import deque, namedtuple
from typing import Dict, List, Optional, Tuple
import random
import warnings
warnings.filterwarnings("ignore")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

Transition = namedtuple("Transition", ["state", "action", "reward", "next_state", "done"])


# ─────────────────────────────────────────────────────────────────
# 1. بيئة التداول المخصصة
# ─────────────────────────────────────────────────────────────────

class TradingEnvironment:
    """
    بيئة تداول كاملة متوافقة مع واجهة Gymnasium.

    الإجراءات (Actions):
      0 = بيع  (SELL)
      1 = احتجاز (HOLD)
      2 = شراء  (BUY)

    الحالة (State):
      نافذة زمنية من الميزات الفنية + الرصيد الحالي
    """

    def __init__(
        self,
        features: np.ndarray,       # (T, n_features)
        prices:   np.ndarray,       # (T,) سعر الإغلاق
        window_size: int = 30,
        initial_balance: float = 100_000.0,
        transaction_cost: float = 0.001,   # 0.1% عمولة
        max_position_pct: float = 0.95,    # أقصى نسبة من الرصيد للاستثمار
        reward_scaling: float = 1.0,
    ):
        self.features         = features
        self.prices           = prices
        self.window_size      = window_size
        self.initial_balance  = initial_balance
        self.transaction_cost = transaction_cost
        self.max_position_pct = max_position_pct
        self.reward_scaling   = reward_scaling

        self.n_features  = features.shape[1]
        self.obs_size    = window_size * self.n_features + 3  # +3: رصيد، موقف، قيمة
        self.action_size = 3
        self.reset()

    def reset(self) -> np.ndarray:
        self.current_step = self.window_size
        self.balance      = self.initial_balance
        self.shares_held  = 0.0
        self.net_worth    = self.initial_balance
        self.prev_worth   = self.initial_balance
        self.trades: List[Dict] = []
        return self._get_obs()

    def _get_obs(self) -> np.ndarray:
        window = self.features[
            self.current_step - self.window_size:self.current_step
        ].flatten()
        portfolio = np.array([
            self.balance / self.initial_balance,
            self.shares_held * self.prices[self.current_step] / self.initial_balance,
            self.net_worth / self.initial_balance
        ])
        return np.concatenate([window, portfolio]).astype(np.float32)

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict]:
        price = self.prices[self.current_step]
        done  = False

        # ── تنفيذ الإجراء ─────────────────────────────────────
        if action == 2:    # شراء
            max_buy = int((self.balance * self.max_position_pct) / (price * (1 + self.transaction_cost)))
            if max_buy > 0:
                cost = max_buy * price * (1 + self.transaction_cost)
                self.balance    -= cost
                self.shares_held += max_buy
                self.trades.append({"step": self.current_step, "type": "BUY",
                                     "price": price, "shares": max_buy})

        elif action == 0:  # بيع
            if self.shares_held > 0:
                revenue = self.shares_held * price * (1 - self.transaction_cost)
                self.balance    += revenue
                self.trades.append({"step": self.current_step, "type": "SELL",
                                     "price": price, "shares": self.shares_held})
                self.shares_held = 0.0

        # ── تحديث القيمة الصافية ───────────────────────────────
        self.net_worth = self.balance + self.shares_held * price
        reward = (self.net_worth - self.prev_worth) / self.initial_balance * self.reward_scaling
        self.prev_worth = self.net_worth

        # مكافأة إضافية للحفاظ على رأس المال
        if self.net_worth < self.initial_balance * 0.7:
            reward -= 0.1
            done    = True

        self.current_step += 1
        if self.current_step >= len(self.prices) - 1:
            done = True

        obs  = self._get_obs() if not done else np.zeros(self.obs_size, dtype=np.float32)
        info = {
            "net_worth": self.net_worth,
            "balance":   self.balance,
            "shares":    self.shares_held,
            "return_pct": (self.net_worth / self.initial_balance - 1) * 100
        }
        return obs, reward, done, info

    def get_performance_metrics(self) -> Dict:
        total_return = (self.net_worth / self.initial_balance - 1) * 100
        n_trades = len(self.trades)
        buy_hold = (self.prices[-1] / self.prices[self.window_size] - 1) * 100
        return {
            "total_return_pct": total_return,
            "buy_hold_return":  buy_hold,
            "alpha":            total_return - buy_hold,
            "n_trades":         n_trades,
            "final_net_worth":  self.net_worth,
        }


# ─────────────────────────────────────────────────────────────────
# 2. ذاكرة الإعادة (Replay Buffer)
# ─────────────────────────────────────────────────────────────────

class ReplayBuffer:
    """ذاكرة الإعادة ذات الأولوية (Prioritized Experience Replay)."""

    def __init__(self, capacity: int = 100_000, alpha: float = 0.6):
        self.capacity  = capacity
        self.alpha     = alpha
        self.buffer    = deque(maxlen=capacity)
        self.priorities = deque(maxlen=capacity)

    def push(self, *args):
        max_priority = max(self.priorities, default=1.0)
        self.buffer.append(Transition(*args))
        self.priorities.append(max_priority)

    def sample(self, batch_size: int, beta: float = 0.4) -> Tuple:
        priorities = np.array(self.priorities, dtype=np.float32) ** self.alpha
        probs      = priorities / priorities.sum()
        indices    = np.random.choice(len(self.buffer), batch_size, p=probs, replace=False)
        samples    = [self.buffer[i] for i in indices]

        weights = (len(self.buffer) * probs[indices]) ** (-beta)
        weights /= weights.max()

        batch = Transition(*zip(*samples))
        return batch, indices, weights

    def update_priorities(self, indices: np.ndarray, errors: np.ndarray):
        for idx, err in zip(indices, errors):
            self.priorities[idx] = abs(err) + 1e-5

    def __len__(self):
        return len(self.buffer)


# ─────────────────────────────────────────────────────────────────
# 3. DQN + Double DQN + Dueling DQN
# ─────────────────────────────────────────────────────────────────

class DuelingDQN(nn.Module):
    """
    Dueling DQN:
      - Stream القيمة V(s) + Stream الميزة A(s, a)
      - Q(s, a) = V(s) + A(s, a) - mean(A)
    """

    def __init__(self, obs_size: int, action_size: int, hidden: int = 256):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(obs_size, hidden), nn.LayerNorm(hidden), nn.ReLU(),
            nn.Linear(hidden, hidden),   nn.LayerNorm(hidden), nn.ReLU(),
            nn.Linear(hidden, hidden // 2)
        )
        self.value_stream = nn.Sequential(
            nn.Linear(hidden // 2, 128), nn.ReLU(),
            nn.Linear(128, 1)
        )
        self.advantage_stream = nn.Sequential(
            nn.Linear(hidden // 2, 128), nn.ReLU(),
            nn.Linear(128, action_size)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.shared(x)
        V    = self.value_stream(feat)
        A    = self.advantage_stream(feat)
        return V + A - A.mean(dim=1, keepdim=True)


class DQNAgent:
    """
    وكيل DQN كامل مع:
      - Double DQN (شبكة مستهدفة)
      - Dueling Architecture
      - Prioritized Replay Buffer
      - Epsilon-Greedy Exploration
    """

    def __init__(
        self,
        obs_size: int,
        action_size: int = 3,
        lr: float = 1e-4,
        gamma: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.995,
        target_update_freq: int = 100,
        batch_size: int = 64,
        buffer_size: int = 50_000
    ):
        self.action_size   = action_size
        self.gamma         = gamma
        self.epsilon       = epsilon_start
        self.eps_end       = epsilon_end
        self.eps_decay     = epsilon_decay
        self.target_update = target_update_freq
        self.batch_size    = batch_size
        self.step_count    = 0

        self.policy_net = DuelingDQN(obs_size, action_size).to(DEVICE)
        self.target_net = DuelingDQN(obs_size, action_size).to(DEVICE)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.AdamW(self.policy_net.parameters(), lr=lr, weight_decay=1e-4)
        self.memory    = ReplayBuffer(buffer_size)
        self.losses: List[float] = []

    def select_action(self, state: np.ndarray) -> int:
        if random.random() < self.epsilon:
            return random.randint(0, self.action_size - 1)
        with torch.no_grad():
            q = self.policy_net(to_tensor(state).unsqueeze(0))
        return q.argmax(1).item()

    def store(self, state, action, reward, next_state, done):
        self.memory.push(state, action, reward, next_state, done)

    def learn(self) -> Optional[float]:
        if len(self.memory) < self.batch_size:
            return None

        batch, indices, weights = self.memory.sample(self.batch_size)
        weights_t = torch.tensor(weights, dtype=torch.float32).to(DEVICE)

        states  = torch.tensor(np.array(batch.state),      dtype=torch.float32).to(DEVICE)
        actions = torch.tensor(batch.action,               dtype=torch.long).to(DEVICE)
        rewards = torch.tensor(batch.reward,               dtype=torch.float32).to(DEVICE)
        n_states = torch.tensor(np.array(batch.next_state),dtype=torch.float32).to(DEVICE)
        dones   = torch.tensor(batch.done,                 dtype=torch.float32).to(DEVICE)

        # Double DQN: اختيار الإجراء من policy_net، تقييمه من target_net
        with torch.no_grad():
            next_actions  = self.policy_net(n_states).argmax(1)
            next_q_values = self.target_net(n_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q      = rewards + self.gamma * next_q_values * (1 - dones)

        current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        td_errors = (current_q - target_q).detach().abs().cpu().numpy()
        self.memory.update_priorities(indices, td_errors)

        loss = (weights_t * F.smooth_l1_loss(current_q, target_q, reduction="none")).mean()
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 10.0)
        self.optimizer.step()

        self.epsilon = max(self.eps_end, self.epsilon * self.eps_decay)
        self.step_count += 1

        if self.step_count % self.target_update == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())

        self.losses.append(loss.item())
        return loss.item()

    def train(self, env: TradingEnvironment, episodes: int = 200) -> List[float]:
        episode_returns = []
        for ep in range(1, episodes + 1):
            state = env.reset()
            total_reward = 0.0
            while True:
                action = self.select_action(state)
                next_state, reward, done, info = env.step(action)
                self.store(state, action, reward, next_state, done)
                self.learn()
                state  = next_state
                total_reward += reward
                if done:
                    break

            metrics = env.get_performance_metrics()
            episode_returns.append(metrics["total_return_pct"])

            if ep % 20 == 0:
                avg_ret = np.mean(episode_returns[-20:])
                print(f"  حلقة {ep:4d} | return={metrics['total_return_pct']:.2f}% "
                      f"| avg_20={avg_ret:.2f}% | ε={self.epsilon:.3f}")
        return episode_returns

    def save(self, path: str):
        torch.save({"policy": self.policy_net.state_dict(),
                    "epsilon": self.epsilon}, path)

    def load(self, path: str):
        ckpt = torch.load(path, map_location=DEVICE)
        self.policy_net.load_state_dict(ckpt["policy"])
        self.target_net.load_state_dict(ckpt["policy"])
        self.epsilon = ckpt.get("epsilon", self.eps_end)


def to_tensor(arr, dtype=torch.float32):
    return torch.tensor(arr, dtype=dtype).to(DEVICE)


# ─────────────────────────────────────────────────────────────────
# 4. PPO (Proximal Policy Optimization)
# ─────────────────────────────────────────────────────────────────

class ActorCritic(nn.Module):
    """شبكة Actor-Critic المشتركة لـ PPO."""

    def __init__(self, obs_size: int, action_size: int, hidden: int = 256):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(obs_size, hidden),     nn.LayerNorm(hidden), nn.Tanh(),
            nn.Linear(hidden, hidden),       nn.LayerNorm(hidden), nn.Tanh(),
            nn.Linear(hidden, hidden // 2),                        nn.Tanh(),
        )
        self.actor  = nn.Linear(hidden // 2, action_size)
        self.critic = nn.Linear(hidden // 2, 1)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        feat = self.shared(x)
        return self.actor(feat), self.critic(feat).squeeze(-1)

    def get_action(self, x: torch.Tensor):
        logits, value = self.forward(x)
        dist   = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        return action, dist.log_prob(action), dist.entropy(), value


class PPOAgent:
    """
    وكيل PPO (Proximal Policy Optimization):
      - Clipped Surrogate Objective
      - GAE (Generalized Advantage Estimation)
      - Entropy Regularization
    """

    def __init__(
        self,
        obs_size: int,
        action_size: int = 3,
        lr: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_eps: float = 0.2,
        entropy_coef: float = 0.01,
        value_coef: float = 0.5,
        n_epochs: int = 10,
        batch_size: int = 64,
        rollout_steps: int = 2048
    ):
        self.gamma        = gamma
        self.gae_lambda   = gae_lambda
        self.clip_eps     = clip_eps
        self.entropy_coef = entropy_coef
        self.value_coef   = value_coef
        self.n_epochs     = n_epochs
        self.batch_size   = batch_size
        self.rollout_steps = rollout_steps

        self.network   = ActorCritic(obs_size, action_size).to(DEVICE)
        self.optimizer = optim.AdamW(self.network.parameters(), lr=lr, eps=1e-5)
        self.scheduler = optim.lr_scheduler.LinearLR(
            self.optimizer, start_factor=1.0, end_factor=0.1, total_iters=1000
        )
        self.losses: List[float] = []

    def _compute_gae(
        self,
        rewards: List[float],
        values:  List[float],
        dones:   List[bool],
        last_value: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """حساب Generalized Advantage Estimation."""
        rewards = np.array(rewards)
        values  = np.array(values + [last_value])
        dones   = np.array(dones)

        advantages = np.zeros_like(rewards)
        gae = 0.0
        for t in reversed(range(len(rewards))):
            delta = rewards[t] + self.gamma * values[t+1] * (1 - dones[t]) - values[t]
            gae   = delta + self.gamma * self.gae_lambda * (1 - dones[t]) * gae
            advantages[t] = gae

        returns = advantages + values[:-1]
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        return advantages, returns

    def update(
        self,
        states:  np.ndarray,
        actions: np.ndarray,
        log_probs_old: np.ndarray,
        advantages: np.ndarray,
        returns:    np.ndarray
    ) -> Dict[str, float]:
        states_t     = torch.tensor(states,         dtype=torch.float32).to(DEVICE)
        actions_t    = torch.tensor(actions,        dtype=torch.long).to(DEVICE)
        log_old_t    = torch.tensor(log_probs_old,  dtype=torch.float32).to(DEVICE)
        advantages_t = torch.tensor(advantages,     dtype=torch.float32).to(DEVICE)
        returns_t    = torch.tensor(returns,        dtype=torch.float32).to(DEVICE)

        total_policy_loss = 0.0
        total_value_loss  = 0.0
        total_entropy     = 0.0
        n_updates = 0

        for _ in range(self.n_epochs):
            indices = np.random.permutation(len(states))
            for start in range(0, len(states), self.batch_size):
                idx  = indices[start:start + self.batch_size]
                logits, values = self.network(states_t[idx])
                dist      = torch.distributions.Categorical(logits=logits)
                log_new   = dist.log_prob(actions_t[idx])
                entropy   = dist.entropy().mean()

                ratio        = torch.exp(log_new - log_old_t[idx])
                surr1        = ratio * advantages_t[idx]
                surr2        = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * advantages_t[idx]
                policy_loss  = -torch.min(surr1, surr2).mean()
                value_loss   = F.mse_loss(values, returns_t[idx])
                loss = policy_loss + self.value_coef * value_loss - self.entropy_coef * entropy

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.network.parameters(), 0.5)
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss  += value_loss.item()
                total_entropy     += entropy.item()
                n_updates += 1

        self.scheduler.step()
        return {
            "policy_loss": total_policy_loss / n_updates,
            "value_loss":  total_value_loss  / n_updates,
            "entropy":     total_entropy     / n_updates,
        }

    def train(self, env: TradingEnvironment, total_steps: int = 100_000) -> List[float]:
        episode_returns = []
        state = env.reset()
        episode_reward = 0.0
        step = 0

        while step < total_steps:
            states, actions, log_probs, rewards, dones, values = [], [], [], [], [], []

            for _ in range(self.rollout_steps):
                state_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    action, log_prob, _, value = self.network.get_action(state_t)
                action   = action.item()
                log_prob = log_prob.item()
                value    = value.item()

                next_state, reward, done, info = env.step(action)
                states.append(state)
                actions.append(action)
                log_probs.append(log_prob)
                rewards.append(reward)
                dones.append(done)
                values.append(value)
                episode_reward += reward
                step += 1

                if done:
                    episode_returns.append(info["return_pct"])
                    state = env.reset()
                    episode_reward = 0.0
                else:
                    state = next_state

                if step >= total_steps:
                    break

            # حساب قيمة الحالة الأخيرة
            with torch.no_grad():
                last_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(DEVICE)
                _, last_val = self.network(last_t)
                last_value  = last_val.item()

            advantages, returns = self._compute_gae(rewards, values, dones, last_value)
            loss_info = self.update(
                np.array(states), np.array(actions),
                np.array(log_probs), advantages, returns
            )

            if len(episode_returns) > 0 and len(episode_returns) % 10 == 0:
                avg = np.mean(episode_returns[-10:])
                print(f"  خطوة {step:6d} | حلقات={len(episode_returns)} "
                      f"| avg_return={avg:.2f}%")

        return episode_returns

    def save(self, path: str):
        torch.save(self.network.state_dict(), path)

    def load(self, path: str):
        self.network.load_state_dict(torch.load(path, map_location=DEVICE))


# ─────────────────────────────────────────────────────────────────
# 5. A2C (Advantage Actor-Critic)
# ─────────────────────────────────────────────────────────────────

class A2CAgent:
    """
    A2C – نسخة متزامنة من A3C (Asynchronous Advantage Actor-Critic).
    أبسط من PPO لكن أسرع في التقارب على بيانات التداول.
    """

    def __init__(
        self,
        obs_size: int,
        action_size: int = 3,
        lr: float = 7e-4,
        gamma: float = 0.99,
        entropy_coef: float = 0.01,
        value_coef: float = 0.5,
        n_steps: int = 5
    ):
        self.gamma        = gamma
        self.entropy_coef = entropy_coef
        self.value_coef   = value_coef
        self.n_steps      = n_steps

        self.network   = ActorCritic(obs_size, action_size).to(DEVICE)
        self.optimizer = optim.RMSprop(self.network.parameters(), lr=lr, eps=1e-5)

    def train_step(
        self,
        states:   np.ndarray,
        actions:  np.ndarray,
        rewards:  List[float],
        dones:    List[bool],
        last_val: float
    ) -> Dict:
        R = last_val
        returns = []
        for r, d in zip(reversed(rewards), reversed(dones)):
            R = r + self.gamma * R * (1 - float(d))
            returns.insert(0, R)

        states_t  = torch.tensor(states,          dtype=torch.float32).to(DEVICE)
        actions_t = torch.tensor(actions,         dtype=torch.long).to(DEVICE)
        returns_t = torch.tensor(returns,         dtype=torch.float32).to(DEVICE)

        logits, values = self.network(states_t)
        dist       = torch.distributions.Categorical(logits=logits)
        log_probs  = dist.log_prob(actions_t)
        entropy    = dist.entropy().mean()
        advantages = returns_t - values.detach()

        policy_loss = -(log_probs * advantages).mean()
        value_loss  = F.mse_loss(values, returns_t)
        loss = policy_loss + self.value_coef * value_loss - self.entropy_coef * entropy

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.network.parameters(), 0.5)
        self.optimizer.step()

        return {
            "loss": loss.item(),
            "policy_loss": policy_loss.item(),
            "value_loss": value_loss.item()
        }

    def train(self, env: TradingEnvironment, total_steps: int = 50_000) -> List[float]:
        episode_returns = []
        state = env.reset()
        episode_reward = 0.0
        step = 0

        while step < total_steps:
            states, actions, rewards, dones = [], [], [], []
            for _ in range(self.n_steps):
                state_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    action, _, _, _ = self.network.get_action(state_t)
                action = action.item()
                next_state, reward, done, info = env.step(action)

                states.append(state)
                actions.append(action)
                rewards.append(reward)
                dones.append(done)
                episode_reward += reward
                step += 1
                state = next_state if not done else env.reset()

                if done:
                    episode_returns.append(info["return_pct"])
                    episode_reward = 0.0
                if step >= total_steps:
                    break

            with torch.no_grad():
                last_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(DEVICE)
                _, last_val = self.network(last_t)
            self.train_step(
                np.array(states), np.array(actions),
                rewards, dones, last_val.item()
            )

        return episode_returns


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_reinforcement_learning():
    print("=" * 60)
    print("  التعلم المعزز للتداول الآلي")
    print("  الجهاز:", DEVICE)
    print("=" * 60)

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_preprocessing import (
        load_market_data, clean_data, add_technical_features,
        add_time_features, create_labels, DataProcessor
    )

    df = load_market_data()
    df = clean_data(df)
    df = add_technical_features(df)
    df = add_time_features(df)
    df = create_labels(df)

    processor = DataProcessor(window_size=30)
    data = processor.prepare(df)

    exclude = {"Open", "High", "Low", "Close", "Volume", "future_return", "label_3class", "label_binary"}
    feat_cols = [c for c in df.columns if c not in exclude]
    features = data["scaler"].transform(df[feat_cols].values)
    prices   = df["Close"].values

    train_end = int(len(prices) * 0.7)
    train_features = features[:train_end]
    train_prices   = prices[:train_end]
    test_features  = features[train_end:]
    test_prices    = prices[train_end:]

    print(f"\nبيانات التدريب: {len(train_prices)} يوم")
    print(f"بيانات الاختبار : {len(test_prices)} يوم")

    # ── DQN ─────────────────────────────────────────────────────
    print("\n[1] تدريب DQN...")
    train_env = TradingEnvironment(train_features, train_prices, window_size=30)
    dqn_agent = DQNAgent(
        obs_size=train_env.obs_size,
        action_size=3,
        epsilon_decay=0.99,
        batch_size=32,
        buffer_size=10_000
    )
    dqn_returns = dqn_agent.train(train_env, episodes=30)
    print(f"    متوسط العائد (آخر 10): {np.mean(dqn_returns[-10:]):.2f}%")

    # اختبار DQN
    test_env = TradingEnvironment(test_features, test_prices, window_size=30)
    state = test_env.reset()
    dqn_agent.epsilon = 0.0  # وضع الاستغلال
    while True:
        action = dqn_agent.select_action(state)
        state, _, done, info = test_env.step(action)
        if done:
            break
    dqn_metrics = test_env.get_performance_metrics()
    print(f"    [اختبار DQN] عائد={dqn_metrics['total_return_pct']:.2f}% "
          f"| B&H={dqn_metrics['buy_hold_return']:.2f}% "
          f"| Alpha={dqn_metrics['alpha']:.2f}%")

    # ── PPO ─────────────────────────────────────────────────────
    print("\n[2] تدريب PPO...")
    train_env2 = TradingEnvironment(train_features, train_prices, window_size=30)
    ppo_agent  = PPOAgent(
        obs_size=train_env2.obs_size,
        rollout_steps=256,
        n_epochs=4,
        batch_size=32
    )
    ppo_returns = ppo_agent.train(train_env2, total_steps=10_000)
    if ppo_returns:
        print(f"    متوسط العائد (PPO): {np.mean(ppo_returns):.2f}%")

    # ── A2C ─────────────────────────────────────────────────────
    print("\n[3] تدريب A2C...")
    train_env3 = TradingEnvironment(train_features, train_prices, window_size=30)
    a2c_agent  = A2CAgent(obs_size=train_env3.obs_size, n_steps=5)
    a2c_returns = a2c_agent.train(train_env3, total_steps=5_000)
    if a2c_returns:
        print(f"    متوسط العائد (A2C): {np.mean(a2c_returns):.2f}%")

    print("\n✅ اكتمل التدريب بنجاح.")


if __name__ == "__main__":
    demo_reinforcement_learning()
