import numpy as np

from mushroom_rl.environments.pybullet_envs.air_hockey.single import AirHockeySingle, PyBulletObservationType


class AirHockeyPrepare(AirHockeySingle):
    """
    Class for the air hockey preparation task.
    The agent tries to improve the puck position to y = 0.
    If the agent looses control of the puck, it will get a punishment.
    """
    def __init__(self, gamma=0.99, horizon=500, env_noise=False, obs_noise=False, obs_delay=False, torque_control=True,
                 step_action_function=None, timestep=1 / 240., n_intermediate_steps=1, debug_gui=False,
                 random_init=False, action_penalty=1e-3, table_boundary_terminate=False, sub_problem="side"):
        """
        Constructor

        Args:
            random_init(bool, False): If true, initialize the puck at random position .
            action_penalty(float, 1e-3): The penalty of the action on the reward at each time step
            sub_problem(string, "side"): determines which area is considered for the initial puck position.
                                        Currently "side" and "bottom" are available
        """

        self.random_init = random_init
        self.action_penalty = action_penalty
        self.sub_problem = sub_problem

        self.start_range = None
        if sub_problem == "side":
            self.start_range = np.array([[-0.8, -0.4], [0.25, 0.46]])
        elif sub_problem == "bottom":
            self.start_range = np.array([[-0.9, -0.8], [0.125, 0.46]])

        self.desired_point = np.array([-0.6, 0])
        self.ee_end_pos = [-8.10001913e-01, -1.43459494e-06]

        self.has_hit = False
        self.has_bounce = False
        self.puck_pos = None

        super().__init__(gamma=gamma, horizon=horizon, timestep=timestep, n_intermediate_steps=n_intermediate_steps,
                         debug_gui=debug_gui, env_noise=env_noise, obs_noise=obs_noise, obs_delay=obs_delay,
                         torque_control=torque_control, step_action_function=step_action_function,
                         table_boundary_terminate=table_boundary_terminate, number_flags=1)

    def setup(self, state):
        if self.random_init:
            puck_pos = np.random.rand(2) * (self.start_range[:, 1] - self.start_range[:, 0]) + self.start_range[:, 0]
            puck_pos *= [1, [1, -1][np.random.randint(2)]]
            # Used for data logging in eval
            self.puck_pos = puck_pos
        else:
            puck_pos = np.mean(self.start_range, axis=1)

        self.desired_point = [puck_pos[0], 0]

        puck_pos = np.concatenate([puck_pos, [-0.189]])
        self.client.resetBasePositionAndOrientation(self._model_map['puck'], puck_pos, [0, 0, 0, 1.0])

        for i, (model_id, joint_id, _) in enumerate(self._indexer.action_data):
            self.client.resetJointState(model_id, joint_id, self.init_state[i])

        self.has_hit = False
        self.has_bounce = False


    def reward(self, state, action, next_state, absorbing):
        puck_pos = self.get_sim_state(next_state, "puck", PyBulletObservationType.BODY_POS)[:2]
        puck_vel = self.get_sim_state(next_state, "puck", PyBulletObservationType.BODY_LIN_VEL)[:2]
        ee_pos = self.get_sim_state(next_state, "planar_robot_1/link_striker_ee",
                                    PyBulletObservationType.LINK_POS)[:2]

        if self.sub_problem == "side":
            # Large bonus for being slow at the end
            if absorbing and abs(puck_pos[1]) < 0.47:
                r = 100 * np.exp(-2 * np.linalg.norm(puck_vel))
                return r

            # After hit
            if self.has_hit:
                if puck_pos[0] < -0.35 and abs(puck_pos[1]) < 0.47:
                    r_vel_x = max([0, 1 - (10 * (np.exp(abs(puck_vel[0])) - 1))])

                    dist_ee_des = np.linalg.norm(ee_pos - self.ee_end_pos)
                    r_ee = 0.5 - dist_ee_des

                    r = r_vel_x + r_ee + 1
                else:
                    r = 0
            # Before hit
            else:
                dist_ee_puck = np.linalg.norm(puck_pos - ee_pos)
                vec_ee_puck = (puck_pos - ee_pos) / dist_ee_puck

                cos_ang = np.clip(vec_ee_puck @ np.array([0, np.copysign(1, puck_pos[1])]), 0, 1)

                r = np.exp(-8 * (dist_ee_puck - 0.08)) * cos_ang ** 2

        # If init_strat is "bottom"
        else:
            if absorbing and puck_pos[0] >= -0.6:
                r = 100 * np.exp(-2 * np.linalg.norm(puck_vel))
                return r

            if self.has_hit:
                if -0.6 > puck_pos[0] > -0.9 and abs(puck_pos[1]) < 0.47:
                    sig = 0.1

                    r_x = 1. / (np.sqrt(2. * np.pi) * sig) * np.exp(-np.power((puck_pos[0] + 0.75) / sig, 2.) / 2)

                    r_y = 2 - abs(puck_vel[1])
                    dist_ee_des = np.linalg.norm(ee_pos - self.ee_end_pos)
                    r_ee = 0.5 * np.exp(-3 * dist_ee_des)
                    r = r_x + r_y + r_ee + 1
                else:
                    r = 0

            else:
                # Before hit

                dist_ee_puck = np.linalg.norm(puck_pos - ee_pos)
                vec_ee_puck = (puck_pos - ee_pos) / dist_ee_puck

                cos_ang_side = np.clip(vec_ee_puck @ np.array([0.2, np.copysign(0.8, puck_pos[1])]), 0, 1)
                cos_ang_bottom = np.clip(vec_ee_puck @ np.array([-1, 0]), 0, 1)
                cos_ang = max([cos_ang_side, cos_ang_bottom])

                r = np.exp(-8 * (dist_ee_puck - 0.08)) * cos_ang ** 2

        r -= self.action_penalty * np.linalg.norm(action)
        return r

    def is_absorbing(self, state):
        if super().is_absorbing(state):
            return True
        if self.sub_problem == "side":
            if self.has_hit:
                puck_pos = self.get_sim_state(self._state, "puck", PyBulletObservationType.BODY_POS)[:2]
                if puck_pos[0] > 0 or abs(puck_pos[1]) < 0.01:
                    return True
            return self.has_bounce
        else:
            if self.has_hit:
                puck_pos = self.get_sim_state(self._state, "puck", PyBulletObservationType.BODY_POS)[:2]
                if puck_pos[0] > 0 or abs(puck_pos[1]) < 0.01:
                    return True
            return False

    def _simulation_post_step(self):
        if not self.has_hit:
            collision_count = len(self.client.getContactPoints(self._model_map['puck'],
                                                               self._indexer.link_map['planar_robot_1/'
                                                                                      'link_striker_ee'][0],
                                                               -1,
                                                               self._indexer.link_map['planar_robot_1/'
                                                                                      'link_striker_ee'][1]))
            if collision_count > 0:
                self.has_hit = True

        if not self.has_bounce:
            collision_count = 0
            collision_count += len(self.client.getContactPoints(self._model_map['puck'],
                                                                self._indexer.link_map['t_up_rim_l'][0],
                                                                -1,
                                                                self._indexer.link_map['t_up_rim_l'][1]))
            collision_count += len(self.client.getContactPoints(self._model_map['puck'],
                                                                self._indexer.link_map['t_up_rim_r'][0],
                                                                -1,
                                                                self._indexer.link_map['t_up_rim_r'][1]))

            collision_count += len(self.client.getContactPoints(self._model_map['puck'],
                                                                self._indexer.link_map['t_down_rim_l'][0],
                                                                -1,
                                                                self._indexer.link_map['t_down_rim_l'][1]))
            collision_count += len(self.client.getContactPoints(self._model_map['puck'],
                                                                self._indexer.link_map['t_down_rim_r'][0],
                                                                -1,
                                                                self._indexer.link_map['t_down_rim_r'][1]))

            if collision_count > 0:
                self.has_bounce = True

    def _create_observation(self, state):
        obs = super(AirHockeyPrepare, self)._create_observation(state)
        return np.append(obs, [self.has_hit])


if __name__ == '__main__':
    import time

    env = AirHockeyPrepare(debug_gui=True, obs_noise=False, obs_delay=False, n_intermediate_steps=4, random_init=True,
                           init_state="bottom")

    R = 0.
    J = 0.
    gamma = 1.
    steps = 0
    env.reset()
    while True:

        # action = np.random.randn(3) * 5
        action = np.array([0, 0, 0])
        observation, reward, done, info = env.step(action)
        gamma *= env.info.gamma
        J += gamma * reward
        R += reward
        steps += 4
        if done or steps > env.info.horizon * 2:
            print("J: ", J, " R: ", R)
            R = 0.
            J = 0.
            gamma = 1.
            steps = 0
            env.reset()
        time.sleep(1 / 60.)