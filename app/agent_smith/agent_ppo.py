import numpy as np
import torch
import torch.nn.functional as F
from torch.distributions import Categorical
import os
import random
from utils.utils import preprocess_ppo


class Policy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.action_space = 3
        self.eps_clip = 0.1

        self.layers = torch.nn.Sequential(
            torch.nn.Linear(9300 * 2, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, 2),
        )
        # self.init_weights()

    # def init_weights(self):
    #     for m in self.modules():
    #         if type(m) is torch.nn.Linear:
    #             torch.nn.init.normal_(m.weight)  #, -1e-3, 1e-3)
    #             torch.nn.init.zeros_(m.bias)

    def convert_action(self, action):
        return action + 2

    def forward(self, d_obs, action=None, action_prob=None, advantage=None, deterministic=False):
        if action is None:
            with torch.no_grad():
                logits = self.layers(d_obs)
                if deterministic:
                    action = int(torch.argmax(logits[0]).detach().cpu().numpy())
                    action_prob = 1.0
                else:
                    c = torch.distributions.Categorical(logits=logits)
                    action = int(c.sample().cpu().numpy()[0])
                    action_prob = float(c.probs[0, action].detach().cpu().numpy())
                return action, action_prob
        '''
        # policy gradient (REINFORCE)
        logits = self.layers(d_obs)
        loss = F.cross_entropy(logits, action, reduction='none') * advantage
        return loss.mean()
        '''

        # PPO
        vs = np.array([[1., 0.], [0., 1.]])
        ts = torch.FloatTensor(vs[action.cpu().numpy()])

        logits = self.layers(d_obs)
        r = torch.sum(F.softmax(logits, dim=1) * ts, dim=1) / action_prob
        loss1 = r * advantage
        loss2 = torch.clamp(r, 1 - self.eps_clip, 1 + self.eps_clip) * advantage
        loss = -torch.min(loss1, loss2)
        loss = torch.mean(loss)

        return loss


class Agent(object):
    def __init__(self, player_id=1):
        # self.train_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.train_device = torch.device("cpu")
        self.policy = Policy().to(self.train_device)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=1e-3)
        self.player_id = player_id
        self.gamma = 0.99
        # self.policy.eval()  # uncomment if testing

        self.states = []
        self.actions = []
        self.action_probs = []
        self.rewards = []

        self.discounted_rewards = []

        self.pp_observation = None
        self.previous_observation = None

    def reset(self):
        pass

    def get_name(self):
        return "Agent Smith"

    def load_model(self):
        try:
            weights = torch.load("../models/model_100.mdl", map_location=torch.device('cpu'))
            self.policy.load_state_dict(weights, strict=False)
        except FileNotFoundError:
            print("Model not found. Check the path and try again.")

    def save_model(self, output_directory, episode=0):
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
        f_name = "{}/model_{}.mdl".format(output_directory, episode)
        torch.save(self.policy.state_dict(), f_name)

    def episode_finished(self):
        R = 0
        self.discounted_rewards = []
        for r in self.rewards[::-1]:
            if r != 0: R = 0  # scored/lost a point in pong, so reset reward sum
            R = r + self.gamma * R
            self.discounted_rewards.insert(0, R)

            # print(discounted_rewards[:5])

        self.discounted_rewards = torch.FloatTensor(self.discounted_rewards)
        self.discounted_rewards = (self.discounted_rewards - self.discounted_rewards.mean()) / self.discounted_rewards.std()

        self.update_policy()

    def store_outcome(self, action, action_prob, reward):
        self.states.append(self.pp_observation)
        self.actions.append(action)
        self.action_probs.append(action_prob)
        self.rewards.append(reward)

    def update_policy(self):
        for _ in range(5):
            n_batch = 24576
            idxs = random.sample(range(len(self.actions)), min(len(self.actions), n_batch))
            d_obs_batch = torch.cat([self.states[idx] for idx in idxs], 0)
            action_batch = torch.LongTensor([self.actions[idx] for idx in idxs])
            action_prob_batch = torch.FloatTensor([self.action_probs[idx] for idx in idxs])
            advantage_batch = torch.FloatTensor([self.discounted_rewards[idx] for idx in idxs])
            # advantage_batch = (advantage_batch - advantage_batch.mean()) / advantage_batch.std()

            self.optimizer.zero_grad()
            loss = self.policy(d_obs_batch, action_batch, action_prob_batch, advantage_batch)
            loss.backward()
            self.optimizer.step()

    def get_action(self, observation, evaluation=False):
        self.pp_observation = preprocess_ppo(observation, self.previous_observation)
        action, action_prob = self.policy(self.pp_observation, deterministic=evaluation)
        self.previous_observation = observation
        return action, action_prob