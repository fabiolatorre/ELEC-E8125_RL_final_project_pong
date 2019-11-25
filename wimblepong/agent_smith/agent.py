import torch
import numpy as np
from torch.distributions import Categorical
import torch
import torch.nn.functional as F
from torch.distributions import Categorical

def discount_rewards(r, gamma):
    discounted_r = torch.zeros_like(r)
    running_add = 0
    for t in reversed(range(0, r.size(-1))):
        running_add = running_add * gamma + r[t]
        discounted_r[t] = running_add
    return discounted_r


class Policy(torch.nn.Module):
    def __init__(self, action_space, hidden=64):
        super().__init__()
        self.action_space = action_space
        self.hidden = hidden

        self.reshaped_size = 1600*1

        self.fc1 = torch.nn.Linear(self.reshaped_size, self.hidden)
        self.fc2 = torch.nn.Linear(self.hidden, self.hidden)
        self.fc3_ac = torch.nn.Linear(self.hidden, action_space)
        self.fc3_cr = torch.nn.Linear(self.hidden, 1)

    def forward(self, x):
        x = self.fc1(x)
        x = F.relu(x)
        x = self.fc2(x)
        x = F.relu(x)

        x_cr = self.fc3_cr(x)

        value = F.relu(x_cr)

        x_mean = self.fc3_ac(x)

        x_probs = F.softmax(x_mean, dim=-1)
        dist = Categorical(x_probs)

        return dist, value


class Agent(object):
    def __init__(self, player_id=1):
        self.train_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.policy = Policy(3).to(self.train_device)
        self.prev_obs = None
        self.player_id = player_id
        self.policy.eval()
        self.gamma = 0.98

        self.states = []
        self.action_probs = []
        self.rewards = []
        self.values = []

    # def replace_policy(self):
    #     self.old_policy.load_state_dict(self.policy.state_dict())

    def get_action(self, observation, evaluation=False):
        x = self.preprocess(observation).to(self.train_device)
        dist, value = self.policy.forward(x)

        if evaluation:
            action = torch.argmax(dist.probs)
        else:
            action = dist.sample()

        self.values.append(value)
        return action

    def reset(self):
        self.prev_obs = None

    def get_name(self):
        return "Agent Smith"

    def load_model(self):
        if torch.cuda.is_available():
            weights = torch.load("model.mdl")
        else:
            weights = torch.load("model.mdl", map_location=torch.device('cpu'))
        self.policy.load_state_dict(weights, strict=False)

    def save_model(self, final=False):
        if not final:
            f_name = "./models/model_training.mdl"
        else:
            f_name = "./models/model_final.mdl"
        torch.save(self.policy.state_dict(), f_name)

    def preprocess(self, observation):
        observation = observation[::5, ::5].mean(axis=-1)
        observation = np.where(observation > 50, 240, 0)

        if self.prev_obs is None:
            self.prev_obs = observation
        else:
            threshold_indices = self.prev_obs >= 80
            self.prev_obs[threshold_indices] -= 80
            self.prev_obs = self.prev_obs + observation

        return torch.from_numpy(self.prev_obs).float().flatten()

    def episode_finished(self):
        action_probs = torch.stack(self.action_probs, dim=0).to(self.train_device).squeeze(-1)
        rewards = torch.stack(self.rewards, dim=0).to(self.train_device).squeeze(-1)
        values = torch.stack(self.values, dim=0).to(self.train_device).squeeze(-1)

        self.states, self.action_probs, self.rewards, self.values = [], [], [], []

        # Compute discounted rewards
        discounted_rewards = discount_rewards(rewards, self.gamma)

        # Compute advantage
        advantage = discounted_rewards - values

        # Normalize advantage
        advantage -= torch.mean(advantage)
        advantage /= torch.std(advantage.detach())

        weighted_probs = - action_probs * advantage.detach()

        # Compute actor and critic loss
        actor_loss = weighted_probs.mean()
        critic_loss = advantage.pow(2).mean()
        ac_loss = actor_loss + critic_loss

        ac_loss.backward()

    def store_outcome(self, observation, action_prob, reward):
        self.states.append(observation)
        self.action_probs.append(action_prob)
        self.rewards.append(torch.Tensor([reward]))



