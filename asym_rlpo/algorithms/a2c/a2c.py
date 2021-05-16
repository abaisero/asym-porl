from typing import Optional

import torch
import torch.nn.functional as F

from asym_rlpo.data import Episode
from asym_rlpo.targets import TargetFunction, td0_target

from .base import A2C_Base, LossesDict


class A2C(A2C_Base):
    model_keys = [
        'action_model',
        'observation_model',
        'history_model',
        'policy_model',
        'vh_model',
    ]

    def losses(
        self,
        episode: Episode,
        *,
        discount: float,
        target_f: Optional[TargetFunction] = None
    ) -> LossesDict:
        if target_f is None:
            target_f = td0_target

        action_features = self.models.action_model(episode.actions)
        action_features = action_features.roll(1, 0)
        action_features[0, :] = 0.0
        observation_features = self.models.observation_model(
            episode.observations
        )

        inputs = torch.cat([action_features, observation_features], dim=-1)
        history_features, _ = self.models.history_model(inputs.unsqueeze(0))
        history_features = history_features.squeeze(0)

        action_logits = self.models.policy_model(history_features)
        vh_values = self.models.vh_model(history_features).squeeze(-1)
        vh_targets = target_f(
            episode.rewards, vh_values.detach(), discount=discount
        )

        discounts = discount ** torch.arange(len(episode), device=self.device)
        action_nlls = -action_logits.gather(
            1, episode.actions.unsqueeze(-1)
        ).squeeze(-1)
        advantages = vh_targets - vh_values.detach()
        actor_loss = (discounts * advantages * action_nlls).sum()

        critic_loss = F.mse_loss(vh_values, vh_targets, reduction='sum')

        action_dists = torch.distributions.Categorical(logits=action_logits)
        negentropy_loss = -action_dists.entropy().sum()

        return {
            'actor': actor_loss,
            'critic': critic_loss,
            'negentropy': negentropy_loss,
        }
